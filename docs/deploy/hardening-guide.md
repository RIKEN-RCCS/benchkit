# Result Portal Hardening Guide

This checklist covers production-facing `result_server` deployments.

## Request Limits

The portal enforces an application-level request body limit:

```text
RESULT_SERVER_MAX_UPLOAD_MB=512
```

Large estimation input archives are also checked per member:

```text
RESULT_SERVER_MAX_ARCHIVE_MEMBER_MB=1024
```

Set these values to match the largest expected PA Data or estimation input
archive. Keep the reverse proxy body limit at or below the Flask limit so that
oversized uploads are rejected before they consume worker memory.

## Rate Limits

API ingest/query routes and admin write routes use Redis-backed fixed-window
rate limits. Production deployments must keep Redis monitored and available;
when Redis is required but unavailable, protected operations fail closed with a
503 response.

Default limits:

- API ingest: 120 requests per runner per minute
- API query: 60 requests per runner per minute
- Admin write actions: 20 requests per admin user per minute

## Reverse Proxy

Run the Flask app behind a reverse proxy that terminates TLS and forwards only
loopback traffic to the app. Keep `/admin/` and `/auth/` protected by portal
authentication; `robots.txt` only reduces crawler noise and is not an access
control mechanism.

## Gunicorn

Use the repository `gunicorn.conf.py` as the baseline process manager
configuration. It binds to `127.0.0.1:8800` by default, sets worker timeouts,
and enables `max_requests` recycling to reduce long-running worker risk.
