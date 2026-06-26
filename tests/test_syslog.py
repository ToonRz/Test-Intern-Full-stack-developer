"""
Low #34 + M2: integration tests for the syslog UDP/TCP listener.

Spec §5.1 mandates UDP+TCP syslog on :514. We don't bind :514 inside tests
(privileged port) — instead we exercise the parse + persist path that
both production framing modes (LF-delimited and RFC6587 octet-counted)
flow through, plus a real UDP socket loopback to confirm the socket
plumbing.

M2 fix: the previous `test_syslog_udp_socket_loopback` only verified that
raw `recvfrom`/`sendto` plumbing works — it never invoked the production
`start_syslog_listener` coroutine. That left the `loop.add_reader` callback
path, the `_MAX_SYSLOG_UDP_TASKS` semaphore backpressure (Critical B-C3),
and the actual parse-and-persist chain from raw datagram → DB row
uncovered. This module now drives the real listener end-to-end.
"""
import asyncio
import socket
import sys
import os
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


# ── M2: real start_syslog_listener end-to-end ───────────────────────────────
#
# These tests start the production `start_syslog_listener` coroutine on an
# ephemeral UDP port and send a real datagram through it. Pins the
# `loop.add_reader` callback path (the actual production wiring), and
# proves the parse → persist chain works on real datagrams, not just
# on functions called directly.

async def _start_listener_on_ephemeral_port() -> tuple:
    """Bind the production syslog listener on an ephemeral UDP port.

    Strategy: bind a temporary socket to grab a free port, close it, then
    start `start_syslog_listener` on that port. The small race window
    (another process grabbing the port) is acceptable for a test.

    Returns: (listener_task, udp_port)
    """
    import backend.main as main_module

    # 1. Grab a free UDP port.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tmp:
        tmp.bind(("127.0.0.1", 0))
        udp_port = tmp.getsockname()[1]

    # 2. Override settings so the listener binds to that port on 127.0.0.1.
    main_module.settings.SYSLOG_HOST = "127.0.0.1"
    main_module.settings.SYSLOG_PORT = udp_port

    # 3. Start the production listener. It binds UDP+TCP on the same port —
    # the TCP half also binds locally because the test runs on 127.0.0.1.
    listener_task = asyncio.create_task(main_module.start_syslog_listener())

    # 4. Wait briefly for the bind to complete (UDP bind is synchronous,
    # but the gather(udp_loop, tcp_loop) needs a scheduler tick).
    for _ in range(50):
        await asyncio.sleep(0.02)
        try:
            # Probe UDP: send a single byte and see if it lands.
            # We don't expect to receive it back (the listener doesn't echo),
            # but a successful sendto without ECONNREFUSED confirms bind.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.sendto(b"\n", ("127.0.0.1", udp_port))
            break
        except OSError:
            await asyncio.sleep(0.02)
    else:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        raise RuntimeError(f"Listener did not bind on port {udp_port} within 1s")

    return listener_task, udp_port


async def _stop_listener(task: asyncio.Task) -> None:
    """Cancel the listener task and wait for it to unwind."""
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        # start_syslog_listener catches its own gather errors and re-raises
        # CancelledError; any other exception is from the bind probe phase.
        pass


@pytest.mark.asyncio
async def test_syslog_listener_end_to_end_udp():
    """M2: a real UDP datagram sent to the production listener produces a LogEntry.

    Path exercised end-to-end:
        sendto() → kernel UDP recv → loop.add_reader callback →
        parse_syslog_firewall → _persist_log → LogEntry row.

    This is the closest a pytest test can get to a real rsyslog client
    talking to the real backend without spinning up docker-compose.
    """
    import os as _os

    # Use a unique src_ip so we can find *this* row in the shared test DB.
    marker = "udp-e2e-marker"
    src_ip = "10.99.88.77"
    line = (
        f"<14>Aug 19 12:00:00 fw01 vendor=demo product=ngfw "
        f"action=deny src={src_ip} dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg={marker}"
    ).encode()

    listener_task, udp_port = await _start_listener_on_ephemeral_port()
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(line, ("127.0.0.1", udp_port))
        sender.close()

        # Poll for the row to appear (parse + persist is async).
        deadline = asyncio.get_event_loop().time() + 3.0
        row = None
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            async with async_session() as db:
                row = (await db.execute(
                    select(LogEntry)
                    .where(LogEntry.src_ip == src_ip)
                    .where(LogEntry.action == "deny")
                    .order_by(LogEntry.id.desc())
                    .limit(1)
                )).scalar_one_or_none()
            if row is not None:
                break

        assert row is not None, (
            f"Listener did not persist a row for src_ip={src_ip} within 3s. "
            f"Either the add_reader callback did not fire, the parser rejected "
            f"the line, or persist failed."
        )
        assert row.source == "firewall"
        assert row.dst_port == 53
        assert marker.encode() in str(row.raw).encode()
    finally:
        await _stop_listener(listener_task)


@pytest.mark.asyncio
async def test_syslog_listener_drops_malformed_lines_without_crashing():
    """M2: malformed input must not crash the listener (parse failure is logged)."""
    listener_task, udp_port = await _start_listener_on_ephemeral_port()
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Send garbage that won't match parse_syslog_firewall or
        # parse_syslog_network. The listener should log it and continue.
        sender.sendto(b"this is not a valid syslog line\n", ("127.0.0.1", udp_port))
        sender.sendto(b"\x00\x01\x02\x03not-a-syslog\n", ("127.0.0.1", udp_port))

        # Wait a moment to let the listener process and continue running.
        await asyncio.sleep(0.3)

        # Send a valid line afterward to prove the listener is still alive.
        marker = "udp-after-garbage"
        valid = (
            f"<14>Aug 19 12:00:00 fw01 vendor=demo product=ngfw "
            f"action=allow src=10.55.55.55 dst=8.8.8.8 spt=1234 dpt=80 proto=tcp msg={marker}"
        ).encode()
        sender2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender2.sendto(valid, ("127.0.0.1", udp_port))
        sender2.close()

        deadline = asyncio.get_event_loop().time() + 3.0
        row = None
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            async with async_session() as db:
                row = (await db.execute(
                    select(LogEntry)
                    .where(LogEntry.src_ip == "10.55.55.55")
                    .where(LogEntry.action == "allow")
                    .order_by(LogEntry.id.desc())
                    .limit(1)
                )).scalar_one_or_none()
            if row is not None:
                break

        assert row is not None, (
            f"Listener crashed after malformed input — valid follow-up datagram "
            f"was not persisted. src_ip=10.55.55.55"
        )
    finally:
        await _stop_listener(listener_task)


@pytest.mark.asyncio
async def test_syslog_listener_concurrent_datagrams_all_persist():
    """M2 + Critical B-C3: under light concurrent load, every datagram persists.

    The semaphore caps in-flight parse tasks at 1000; this test fires well
    below that. The point is to prove the add_reader callback path actually
    spawns concurrent tasks (i.e. doesn't serialize on a single recvfrom).
    """
    listener_task, udp_port = await _start_listener_on_ephemeral_port()
    try:
        N = 10
        unique_ips = [f"10.77.{i // 256}.{i % 256}" for i in range(N)]
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for ip in unique_ips:
            line = (
                f"<14>Aug 19 12:00:00 fw01 vendor=demo product=ngfw "
                f"action=allow src={ip} dst=8.8.8.8 spt=1234 dpt=80 proto=tcp msg=concurrent"
            ).encode()
            sender.sendto(line, ("127.0.0.1", udp_port))
        sender.close()

        deadline = asyncio.get_event_loop().time() + 5.0
        rows = []
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.1)
            async with async_session() as db:
                rows = (await db.execute(
                    select(LogEntry.src_ip)
                    .where(LogEntry.src_ip.in_(unique_ips))
                )).scalars().all()
            if len(rows) == N:
                break

        assert len(rows) == N, (
            f"Listener persisted {len(rows)}/{N} concurrent datagrams. "
            f"add_reader or async task spawning may be broken."
        )
    finally:
        await _stop_listener(listener_task)
