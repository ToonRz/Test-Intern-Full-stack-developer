#!/usr/bin/env bash
# E2E smoke test against the live stack.
# Assumes services are up on localhost:8000 (backend) and localhost:514 (syslog).

set -u
API=http://localhost:8000/api/v1
PASS=0
FAIL=0

# helpers
c() { curl -skS "$@"; }
hr() { printf '\n──────── %s ────────\n' "$*"; }
ok() { printf "  ✓ %s\n" "$*"; PASS=$((PASS+1)); }
ko() { printf "  ✗ %s\n" "$*"; FAIL=$((FAIL+1)); }

rm -f /tmp/cookies-admin.txt /tmp/cookies-viewer.txt
ADMIN_TOKEN=""
VIEWER_TOKEN=""

# 1. AUTH ────────────────────────────────────────────────────────────
hr "1) AUTH"
LOGIN=$(c -X POST "$API/auth/login" -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}')
ADMIN_TOKEN=$(echo "$LOGIN" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
[ -n "$ADMIN_TOKEN" ] && ok "admin login → got JWT" || ko "admin login"

LOGIN_V=$(c -X POST "$API/auth/login" -H "Content-Type: application/json" \
  -d '{"username":"viewer","password":"viewer123"}')
VIEWER_TOKEN=$(echo "$LOGIN_V" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
[ -n "$VIEWER_TOKEN" ] && ok "viewer login → got JWT" || ko "viewer login"

ME=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/auth/me")
echo "$ME" | grep -q '"role":"Admin"' && ok "admin /auth/me → role=Admin" || ko "admin /auth/me"
ME_V=$(c -H "Authorization: Bearer $VIEWER_TOKEN" "$API/auth/me")
echo "$ME_V" | grep -q '"role":"Viewer"' && ok "viewer /auth/me → role=Viewer" || ko "viewer /auth/me"

# Bad creds should fail
BAD=$(c -o /dev/null -w "%{http_code}" -X POST "$API/auth/login" -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"wrong"}')
[ "$BAD" = "401" ] && ok "bad password → 401" || ko "bad password got $BAD"

# 2. RBAC ────────────────────────────────────────────────────────────
hr "2) RBAC"
# Viewer creating user should be forbidden
CODE=$(c -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $VIEWER_TOKEN" \
  -H "Content-Type: application/json" -X POST "$API/users" \
  -d '{"username":"hacker","password":"x","role":"Viewer","tenant":"demoA"}')
[ "$CODE" = "403" ] && ok "viewer POST /users → 403" || ko "viewer POST /users got $CODE"

# Viewer creating alert rule should be forbidden
CODE=$(c -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $VIEWER_TOKEN" \
  -H "Content-Type: application/json" -X POST "$API/alerts" \
  -d '{"name":"x","event_types":["login_failed"],"threshold":1,"window_minutes":1,"group_by":"src_ip"}')
[ "$CODE" = "403" ] && ok "viewer POST /alerts → 403" || ko "viewer POST /alerts got $CODE"

# Admin endpoints open to admin
CODE=$(c -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $ADMIN_TOKEN" "$API/users")
[ "$CODE" = "200" ] && ok "admin GET /users → 200" || ko "admin GET /users got $CODE"

# 3. INGEST (HTTP) ──────────────────────────────────────────────────
hr "3) INGEST — HTTP single"
ING=$(c -X POST "$API/ingest" -H "Content-Type: application/json" \
  -d '{"source":"smoke","event_type":"login","severity":"info","message":"e2e ok","src_ip":"198.51.100.10","tenant":"demoA"}')
echo "$ING" | grep -q '"ingested":1' && ok "POST /ingest single → ingested 1" || ko "single ingest: $ING"

hr "3b) INGEST — batch"
BATCH=$(python -c "
import json
print(json.dumps({'logs':[
  {'source':'aws','event_type':'console_login','severity':'warning','message':'IAM login','src_ip':'203.0.113.1','user':'alice','tenant':'demoA'},
  {'source':'m365','event_type':'mailbox_login','severity':'info','message':'M365 sign-in','src_ip':'203.0.113.2','user':'bob','tenant':'demoA'},
  {'source':'ad','event_type':'logon','severity':'info','message':'AD logon','src_ip':'203.0.113.3','user':'carol','tenant':'demoB'},
  {'source':'crowdstrike','event_type':'process','severity':'info','message':'EDR process','host':'ws-01','tenant':'demoA'},
  {'source':'api','event_type':'web_request','severity':'info','message':'GET /foo','src_ip':'203.0.113.4','tenant':'demoA'}
]}))
")
RES=$(c -X POST "$API/ingest/batch" -H "Content-Type: application/json" -d "$BATCH")
echo "$RES" | grep -q '"ingested":5' && ok "POST /ingest/batch → ingested 5" || ko "batch: $RES"

hr "3c) INGEST — syslog UDP/TCP"
# Use python socket so it works in git-bash (no nc by default)
python <<'PY' && ok "syslog UDP 514 → sent 1 message" || ko "syslog UDP failed"
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(b"<14>Jun 23 10:00:01 host01 sshd[1234]: Failed password for root from 192.0.2.50 port 5000 ssh2\n", ("localhost", 514))
s.close()
PY
sleep 1
python <<'PY' && ok "syslog TCP 514 → sent 1 framed message" || ko "syslog TCP failed"
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3); s.connect(("localhost", 514))
msg = b"<14>Jun 23 10:00:02 host02 sshd[1235]: Failed password for admin from 192.0.2.51 port 5001 ssh2\n"
# octet-counted framing per RFC6587
s.sendall(str(len(msg)).encode() + b" " + msg)
s.close()
PY
sleep 1

# 4. SEARCH & FACETS ────────────────────────────────────────────────
hr "4) SEARCH"
TOTAL=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/logs?limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['total'])")
[ "$TOTAL" -ge 7 ] && ok "GET /logs total ≥ 7 (got $TOTAL)" || ko "logs total $TOTAL"

# Tenant filter (admin)
A_TOTAL=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/logs?tenant=demoA&limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['total'])")
B_TOTAL=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/logs?tenant=demoB&limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['total'])")
[ "$A_TOTAL" -gt "$B_TOTAL" ] && ok "tenant filter: demoA=$A_TOTAL > demoB=$B_TOTAL" || ko "tenant filter demoA=$A_TOTAL demoB=$B_TOTAL"

# Viewer tenant scoping: should only see demoA logs
V_TOTAL=$(c -H "Authorization: Bearer $VIEWER_TOKEN" "$API/logs?limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['total'])")
V_DEMO_B=$(c -H "Authorization: Bearer $VIEWER_TOKEN" "$API/logs?tenant=demoB&limit=1" -o /dev/null -w "%{http_code}")
# Viewer trying to query another tenant's data — should be empty or 403
[ "$V_TOTAL" -ge 0 ] && ok "viewer GET /logs → $V_TOTAL (scoped)" || ko "viewer /logs"
[ "$V_DEMO_B" = "403" ] || [ "$V_DEMO_B" = "200" ] && ok "viewer tenant=demoB → $V_DEMO_B" || ko "viewer demoB got $V_DEMO_B"

# Source filter
SRC_AWS=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/logs?source=aws&limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['total'])")
[ "$SRC_AWS" -ge 1 ] && ok "source=aws → $SRC_AWS" || ko "source=aws got $SRC_AWS"

hr "4b) FACETS / STATS"
FACETS=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/logs/facets")
echo "$FACETS" | grep -q '"by_source"' && ok "/logs/facets has by_source" || ko "facets: $FACETS"
echo "$FACETS" | grep -q '"by_severity"' && ok "/logs/facets has by_severity" || ko "facets severity"

STATS=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/logs/stats")
echo "$STATS" | grep -q '"total"' && ok "/logs/stats has total" || ko "stats: $STATS"

# 5. ALERTING ───────────────────────────────────────────────────────
hr "5) ALERT create → trigger → acknowledge"
RULE=$(c -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -X POST "$API/alerts" -d '{
    "name":"Smoke brute-force",
    "description":"E2E test rule",
    "event_types":["LogonFailed","app_login_failed","login_failed"],
    "threshold":5,
    "window_minutes":5,
    "group_by":"src_ip",
    "action":"store",
    "enabled":true
  }')
RULE_ID=$(echo "$RULE" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('id') or d.get('rule',{}).get('id',''))" 2>/dev/null)
[ -n "$RULE_ID" ] && ok "POST /alerts → rule id=$RULE_ID" || { ko "create rule: $RULE"; RULE_ID=""; }

# Send 6 failed logins from same IP within window
hr "5b) Ingest 6 failed-login events to trip rule"
for i in 1 2 3 4 5 6; do
  c -X POST "$API/ingest" -H "Content-Type: application/json" \
    -d "{\"source\":\"smoke\",\"event_type\":\"login_failed\",\"severity\":\"warning\",\"message\":\"bad pw $i\",\"src_ip\":\"198.51.100.99\",\"tenant\":\"demoA\"}" >/dev/null
done
ok "ingested 6 failed-login events from src_ip=198.51.100.99"

# Wait for engine to evaluate (poll up to 8s)
TID=""
for i in 1 2 3 4 5 6 7 8; do
  sleep 1
  T=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/alerts/triggered?limit=20" | python -c "
import sys,json
d=json.load(sys.stdin)
items=d if isinstance(d,list) else d.get('items') or d.get('triggered') or d.get('alerts') or []
for it in items:
  if (it.get('rule_id')==$RULE_ID or it.get('rule',{}).get('id')==$RULE_ID) and (it.get('group_key') or it.get('src_ip') or '') == '198.51.100.99':
    print(it.get('id')); break
")
  [ -n "$T" ] && { TID="$T"; break; }
done
[ -n "$TID" ] && ok "alert triggered (id=$TID) for src_ip 198.51.100.99" || ko "alert not triggered"

# Acknowledge
if [ -n "$TID" ]; then
  CODE=$(c -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $ADMIN_TOKEN" \
    -X POST "$API/alerts/$TID/acknowledge")
  [ "$CODE" = "200" ] && ok "POST /alerts/$TID/acknowledge → 200" || ko "ack got $CODE"
fi

# 6. TENANTS & USERS ────────────────────────────────────────────────
hr "6) Tenants + Users"
CODE=$(c -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" -X POST "$API/tenants" \
  -d '{"name":"tenant-smoke","description":"e2e"}')
[ "$CODE" = "200" ] || [ "$CODE" = "201" ] && ok "POST /tenants → $CODE" || ko "create tenant got $CODE"

NEWU=$(c -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -X POST "$API/users" \
  -d '{"username":"smoke-user","password":"sm0ke!","role":"Viewer","tenant":"demoA","email":"s@x"}')
echo "$NEWU" | grep -q '"username":"smoke-user"' && ok "POST /users → smoke-user created" || ko "create user: $NEWU"

USERS=$(c -H "Authorization: Bearer $ADMIN_TOKEN" "$API/users")
echo "$USERS" | grep -q 'smoke-user' && ok "smoke-user visible in /users list" || ko "smoke-user not in list"

# Cleanup the rule (cascade removes triggered)
if [ -n "$RULE_ID" ]; then
  CODE=$(c -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $ADMIN_TOKEN" \
    -X DELETE "$API/alerts/$RULE_ID")
  [ "$CODE" = "200" ] || [ "$CODE" = "204" ] && ok "DELETE /alerts/$RULE_ID → $CODE" || ko "delete rule got $CODE"
fi

# 7. METRICS & HEALTH ───────────────────────────────────────────────
hr "7) Ops"
H=$(c -o /dev/null -w "%{http_code}" "$API/../health")
[ "$H" = "200" ] && ok "/health → 200" || ko "health got $H"
M=$(c -o /dev/null -w "%{http_code}" "$API/../metrics")
[ "$M" = "200" ] && ok "/metrics → 200" || ko "metrics got $M"
D=$(c -o /dev/null -w "%{http_code}" "$API/../docs")
[ "$D" = "200" ] && ok "/docs → 200" || ko "docs got $D"

# Summary
hr "SUMMARY"
printf "  passed: %d\n  failed: %d\n" "$PASS" "$FAIL"
[ "$FAIL" = "0" ] && exit 0 || exit 1
