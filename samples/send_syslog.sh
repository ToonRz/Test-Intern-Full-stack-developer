#!/bin/bash
# send_syslog.sh - Send sample syslog per spec.md section 4.1-4.2
# Multi-tenant: demoA, demoB
# Usage: ./send_syslog.sh [host] [port]

HOST="${1:-localhost}"
PORT="${2:-514}"

echo "=== Sending Syslog to $HOST:$PORT ==="

# 4.1 Firewall/Syslog (demoA)
echo '<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg=DNS blocked policy=Block-DNS' | nc -u -w1 "$HOST" "$PORT"
echo "  Firewall (demoA): DNS blocked"

echo '<134>Aug 20 12:45:01 fw01 vendor=demo product=ngfw action=allow src=10.0.1.20 dst=1.2.3.4 spt=443 dpt=443 proto=tcp msg=HTTPS allowed policy=Allow-Outbound' | nc -u -w1 "$HOST" "$PORT"
echo "  Firewall (demoA): HTTPS allowed"

echo '<134>Aug 20 12:46:30 fw01 vendor=demo product=ngfw action=deny src=10.0.1.30 dst=5.6.7.8 spt=22 dpt=22 proto=tcp msg=SSH blocked policy=Block-SSH' | nc -u -w1 "$HOST" "$PORT"
echo "  Firewall (demoA): SSH blocked"

# 4.2 Network Router Syslog (demoA)
echo '<190>Aug 20 13:01:02 r1 if=ge-0/0/1 event=link-down mac=aa:bb:cc:dd:ee:ff reason=carrier-loss' | nc -u -w1 "$HOST" "$PORT"
echo "  Network (demoA): link-down"

echo '<190>Aug 20 13:05:00 r1 if=ge-0/0/2 event=link-up mac=aa:bb:cc:dd:ee:00 reason=connected' | nc -u -w1 "$HOST" "$PORT"
echo "  Network (demoA): link-up"

# 4.1 Firewall (demoB - different tenant)
echo '<134>Aug 20 14:00:00 fw02 vendor=paloalton product=pan-os action=deny src=192.168.1.100 dst=104.16.123.1 spt=54321 dpt=443 proto=tcp msg=Threat blocked policy=Block-Malware' | nc -u -w1 "$HOST" "$PORT"
echo "  Firewall (demoB): Threat blocked"

echo '<134>Aug 20 14:01:00 fw02 vendor=paloalton product=pan-os action=allow src=192.168.1.200 dst=8.8.8.8 spt=12345 dpt=53 proto=udp msg=DNS allowed policy=Allow-DNS' | nc -u -w1 "$HOST" "$PORT"
echo "  Firewall (demoB): DNS allowed"

echo ""
echo "=== Done! Sent 7 syslog messages ==="
echo "Tenants: demoA (5), demoB (2) [syslog uses default tenant in schema]"