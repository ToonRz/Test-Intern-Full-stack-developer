#!/bin/bash
# send_syslog.sh - Send sample syslog via UDP + TCP
# Tests 3 transports: UDP, TCP LF-delimited, TCP RFC6587 octet-counted
# Multi-tenant: demoA, demoB
# Usage: ./send_syslog.sh [host] [port]

HOST="${1:-localhost}"
PORT="${2:-514}"

echo "=== Sending Syslog to $HOST:$PORT ==="

# ── 4.1 Firewall/Syslog via UDP (demoA) ─────────────────────────────────
echo '<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg=DNS-blocked policy=Block-DNS' | nc -u -w1 "$HOST" "$PORT"
echo "  UDP  Firewall (demoA): DNS blocked"

echo '<134>Aug 20 12:45:01 fw01 vendor=demo product=ngfw action=allow src=10.0.1.20 dst=1.2.3.4 spt=443 dpt=443 proto=tcp msg=HTTPS-allowed policy=Allow-Outbound' | nc -u -w1 "$HOST" "$PORT"
echo "  UDP  Firewall (demoA): HTTPS allowed"

# ── 4.2 Router Syslog via TCP — RFC6587 §3.4.1 octet-counted (demoA) ───
# Format: "<byte-count> <message>\n" — note the SPACE between count and message.
msg='<190>Aug 20 13:01:02 r1 if=ge-0/0/1 event=link-down mac=aa:bb:cc:dd:ee:ff reason=carrier-loss'
printf '%d %s\n' "${#msg}" "$msg" | nc -w1 "$HOST" "$PORT"
echo "  TCP  Router (demoA): link-down (octet-counted)"

msg='<190>Aug 20 13:05:00 r1 if=ge-0/0/2 event=link-up mac=aa:bb:cc:dd:ee:00 reason=connected'
printf '%d %s\n' "${#msg}" "$msg" | nc -w1 "$HOST" "$PORT"
echo "  TCP  Router (demoA): link-up (octet-counted)"

# ── 4.1 Firewall via TCP — LF-delimited framing (demoB) ─────────────────
echo '<134>Aug 20 14:00:00 fw02 vendor=paloalton product=pan-os action=deny src=192.168.1.100 dst=104.16.123.1 spt=54321 dpt=443 proto=tcp msg=Threat-blocked policy=Block-Malware' | nc -w1 "$HOST" "$PORT"
echo "  TCP  Firewall (demoB): Threat blocked (LF-delimited)"

echo '<134>Aug 20 14:01:00 fw02 vendor=paloalton product=pan-os action=allow src=192.168.1.200 dst=8.8.8.8 spt=12345 dpt=53 proto=udp msg=DNS-allowed policy=Allow-DNS' | nc -w1 "$HOST" "$PORT"
echo "  TCP  Firewall (demoB): DNS allowed (LF-delimited)"

# ── 4.1 Firewall UDP (demoB) ────────────────────────────────────────────
echo '<134>Aug 20 14:02:00 fw02 vendor=paloalton product=pan-os action=deny src=10.10.10.10 dst=203.0.113.1 spt=9999 dpt=22 proto=tcp msg=SSH-blocked policy=Block-SSH' | nc -u -w1 "$HOST" "$PORT"
echo "  UDP  Firewall (demoB): SSH blocked"

echo ""
echo "=== Done! Sent 7 syslog messages (3 UDP + 4 TCP) ==="
echo "Transports: UDP, TCP LF-delimited, TCP RFC6587 octet-counted"
echo "Tenants: demoA (4), demoB (3)"