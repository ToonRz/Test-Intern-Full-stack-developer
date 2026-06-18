# Ingest - Log Management System

Collector/Ingest layer per spec.md sections 2, 3.

## Log Sources Supported

| Source | Protocol | Status |
|---|---|---|
| Firewall | Syslog UDP/TCP 514 | REAL |
| Network Router | Syslog UDP/TCP 514 | REAL |
| API | HTTP POST /ingest | REAL |
| CrowdStrike | File batch JSON | Sample |
| AWS CloudTrail | File batch JSON | Sample |
| Microsoft 365 | File batch JSON | Sample |
| Microsoft AD | File batch JSON | Sample |

## Normalization

All logs normalize to central schema per spec.md section 3.

## Usage

The ingest layer is embedded in the backend via `POST /ingest` and syslog listener on port 514.

For standalone collection, use Vector or Fluent Bit configured to forward to `/ingest`.
