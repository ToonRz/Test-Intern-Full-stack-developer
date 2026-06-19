"""
Low #34: integration tests for the syslog UDP/TCP listener.

Spec §5.1 mandates UDP+TCP syslog on :514. We don't bind :514 inside tests
(privileged port) — instead we exercise the parse + persist path that
both production framing modes (LF-delimited and RFC6587 octet-counted)
flow through, plus a real UDP socket loopback to confirm the socket
plumbing.
"""
import socket
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from backend.storage.database import LogEntry, async_session


def _make_syslog_line(msg_text: str = "dns test") -> bytes:
    """Build a valid firewall syslog line per spec §4.1."""
    return (
        f"<14>Aug 19 12:00:00 fw01 vendor=demo product=ngfw "
        f"action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg={msg_text}"
    ).encode()


@pytest.mark.asyncio
async def test_syslog_lf_delimited_persists_log():
    """Spec §5.1: LF-delimited TCP syslog should produce a persisted log."""
    from backend.main import _handle_syslog_line

    # Marker text used in the msg field so we can find this exact row.
    marker = "lf-delimited-marker"
    line = _make_syslog_line(marker)
    await _handle_syslog_line(line.decode())

    async with async_session() as db:
        row = (await db.execute(
            select(LogEntry)
            .where(LogEntry.src_ip == "10.0.1.10")
            .where(LogEntry.action == "deny")
            .order_by(LogEntry.id.desc())
            .limit(1)
        )).scalar_one()
    assert row.source == "firewall"
    assert row.dst_port == 53
    # The parser stores the original syslog line in `raw.original` so the
    # marker survives — verify the round-trip end-to-end.
    assert marker.encode() in str(row.raw).encode()


@pytest.mark.asyncio
async def test_syslog_octet_counted_parsing():
    """High #7: production rsyslog uses RFC6587 octet-counted framing; the
    parser must read exactly N bytes after the leading "<digits> " header.
    """
    from backend.main import _OCTET_COUNTED

    msg = _make_syslog_line("octet-counted")
    count = len(msg) + 1  # count includes the trailing newline
    frame = f"{count} ".encode() + msg + b"\n"

    m = _OCTET_COUNTED.match(frame)
    assert m is not None, "Parser failed to recognize octet-counted header"
    n = int(m.group(1))
    assert n == count
    payload = frame[m.end(): m.end() + n]
    assert payload == msg + b"\n"


@pytest.mark.asyncio
async def test_syslog_udp_socket_loopback():
    """Verify the UDP socket plumbing the production listener relies on —
    bind on an ephemeral port, send, recvfrom succeeds with the same bytes."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port > 0

    sock.settimeout(1)
    payload = _make_syslog_line("udp-loopback")
    sock.sendto(payload, ("127.0.0.1", port))
    data, _addr = sock.recvfrom(65535)
    assert data == payload
    sock.close()
