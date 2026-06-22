#!/usr/bin/env python3
"""
post_logs.py - Send ALL sample logs via HTTP POST per spec.md section 4
Multi-tenant: demoA, demoB

Usage:
    python post_logs.py [api_url]
    python post_logs.py http://localhost:8000/api/v1/ingest
    python post_logs.py http://backend:8000/api/v1/ingest  # Docker network
"""
import urllib.request
import ssl
import json
import sys
from datetime import datetime, timezone


API_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v1/ingest"

# Self-signed cert in local dev → skip verification. Production URLs with
# valid certs work normally; only HTTPS hosts that fail validation take
# the unverified path.
_SSL_CTX = ssl.create_default_context()
if API_URL.startswith("https://") and ("localhost" in API_URL or "127.0.0.1" in API_URL):
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE


def post_log(log_data):
    """POST single log to /ingest"""
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(log_data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


def post_batch(logs):
    """POST batch of logs"""
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(logs).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

# ============================================================
# 4.3 HTTP API (POST /ingest) - Login Failed per spec
# ============================================================
print("=== 4.3 HTTP API - app_login_failed (demoA) ===")
post_log({
    "tenant": "demoA",
    "source": "api",
    "event_type": "app_login_failed",
    "user": "alice",
    "ip": "203.0.113.7",
    "reason": "wrong_password",
    "@timestamp": ts
})

# ============================================================
# Brute-force simulation (demoA) - 6 failures from same IP
# ============================================================
print("\n=== Brute-force Detection (demoA) - 6 login failures ===")
for i in range(6):
    post_log({
        "tenant": "demoA",
        "source": "api",
        "event_type": "app_login_failed",
        "user": "eve",
        "ip": "192.0.2.100",
        "reason": "wrong_password",
        "@timestamp": ts
    })

# ============================================================
# 4.4 CrowdStrike (demoA)
# ============================================================
print("\n=== 4.4 CrowdStrike (demoA) ===")
post_batch([
    {
        "tenant": "demoA",
        "source": "crowdstrike",
        "event_type": "malware_detected",
        "host": "WIN10-01",
        "process": "powershell.exe",
        "severity": 8,
        "action": "quarantine",
        "@timestamp": ts
    },
    {
        "tenant": "demoA",
        "source": "crowdstrike",
        "event_type": "process_created",
        "host": "WIN10-02",
        "process": "cmd.exe",
        "user": "administrator",
        "severity": 6,
        "action": "detect",
        "@timestamp": ts
    }
])

# ============================================================
# 4.5 AWS CloudTrail (demoB)
# ============================================================
print("\n=== 4.5 AWS CloudTrail (demoB) ===")
post_batch([
    {
        "tenant": "demoB",
        "source": "aws",
        "cloud": { "service": "iam", "account_id": "123456789012", "region": "ap-southeast-1" },
        "event_type": "CreateUser",
        "user": "admin",
        "@timestamp": ts,
        "raw": { "eventName": "CreateUser", "requestParameters": { "userName": "temp-user" } }
    },
    {
        "tenant": "demoB",
        "source": "aws",
        "cloud": { "service": "ec2", "account_id": "123456789012", "region": "ap-southeast-1" },
        "event_type": "RunInstances",
        "user": "admin",
        "@timestamp": ts,
        "raw": { "eventName": "RunInstances", "requestParameters": { "instanceType": "t2.micro" } }
    }
])

# ============================================================
# 4.6 Microsoft 365 (demoB)
# ============================================================
print("\n=== 4.6 Microsoft 365 (demoB) ===")
post_batch([
    {
        "tenant": "demoB",
        "source": "m365",
        "event_type": "UserLoggedIn",
        "user": "bob@demo.local",
        "ip": "198.51.100.23",
        "status": "Success",
        "workload": "Exchange",
        "@timestamp": ts
    },
    {
        "tenant": "demoB",
        "source": "m365",
        "event_type": "UserLoginFailed",
        "user": "alice@demo.local",
        "ip": "203.0.113.50",
        "status": "Fail",
        "workload": "AzureAD",
        "@timestamp": ts
    }
])

# ============================================================
# 4.7 Microsoft AD / Windows Security (demoA)
# ============================================================
print("\n=== 4.7 Microsoft AD (demoA) ===")
post_batch([
    {
        "tenant": "demoA",
        "source": "ad",
        "event_id": 4625,
        "event_type": "LogonFailed",
        "user": "demo\\eve",
        "host": "DC01",
        "ip": "203.0.113.77",
        "logon_type": 3,
        "@timestamp": ts
    },
    {
        "tenant": "demoA",
        "source": "ad",
        "event_id": 4624,
        "event_type": "LogonSuccess",
        "user": "demo\\admin",
        "host": "DC01",
        "ip": "10.0.0.50",
        "logon_type": 3,
        "@timestamp": ts
    }
])

# ============================================================
# More API logs for demoB
# ============================================================
print("\n=== More API logs (demoB) ===")
for i in range(3):
    post_log({
        "tenant": "demoB",
        "source": "api",
        "event_type": "api_access",
        "user": "bob",
        "ip": "198.51.100.25",
        "@timestamp": ts
    })

print("\n=== Done! Sent all sample logs from spec.md ===")
print("Tenants: demoA, demoB")
print("Sources: api, crowdstrike, aws, m365, ad")