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

Run Gunicorn under systemd with explicit worker, bind, timeout, and recycling
settings that match the deployment. The current `result_server` modules use
repo-local top-level imports (`routes.*`, `utils.*`), so set `PYTHONPATH` to the
`result_server` directory when importing the app as `benchkit.result_server.app`.
Keep stdout/stderr captured by journald or an append-only service log so
`benchkit.audit` JSON Lines emitted on stderr are retained.

Example options:

```text
WorkingDirectory=<deploy-root>
Environment=PYTHONPATH=<deploy-root>/benchkit/result_server
ExecStart=<venv>/bin/gunicorn \
  -w 2 \
  -b 127.0.0.1:8800 \
  --timeout 60 \
  --max-requests 1000 \
  benchkit.result_server.app:app
```

An equivalent direct import form is:

```text
gunicorn --chdir <deploy-root>/benchkit/result_server \
  -w 2 \
  -b 127.0.0.1:8800 \
  --timeout 60 \
  --max-requests 1000 \
  app:app
```

Both styles work with the current tree because Python 3.3+ can import
`benchkit.result_server.app` as a namespace package without `__init__.py` files,
while the existing `from routes.*` and `from utils.*` imports are resolved by
putting `benchkit/result_server` on `PYTHONPATH` or making it the working
directory.

For deployments that want a separate audit file in addition to stderr capture,
set:

```text
RESULT_SERVER_AUDIT_LOG_FILE=/path/to/audit.jsonl
```

The service user must be able to append to that file. Keep rotation and access
controls in the systemd/logrotate or log aggregation layer.
