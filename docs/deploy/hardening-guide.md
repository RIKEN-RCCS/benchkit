# Result Portal Hardening Guide

This checklist covers production-facing `result_server` deployments.

## Request Limits

The portal enforces an application-level request body limit:

```text
RESULT_SERVER_MAX_UPLOAD_MB=512
```

Large estimation artifact archives are also checked per member:

```text
RESULT_SERVER_MAX_ARCHIVE_MEMBER_MB=1024
```

Set these values to match the largest expected PA Data or estimation artifact
archive. Keep the reverse proxy body limit at or below the Flask limit so that
oversized uploads are rejected before they consume worker memory.

## Rate Limits

Login POST, API ingest/query routes, and admin write routes use Redis-backed
fixed-window rate limits. Production deployments must keep Redis monitored and
available; when Redis is required but unavailable, protected operations fail
closed with a 503 response.

Default limits:

- Login verification: 20 requests per client source per minute
- API ingest: 120 requests per runner per minute
- API query: 60 requests per runner per minute
- Admin write actions: 20 requests per admin user per minute

Login failures also maintain a short-lived per-email counter for audit and
alerting context, but the counter does not hard-lock the account. This avoids a
targeted lockout DoS where an attacker can repeatedly close a known user's
login window; volume control is enforced by the source-scoped login limit.

## Reverse Proxy

Run the Flask app behind a reverse proxy that terminates TLS and forwards only
loopback traffic to the app. Keep `/admin/` and `/auth/` protected by portal
authentication; `robots.txt` only reduces crawler noise and is not an access
control mechanism.

`app.py` trusts one reverse proxy hop with Werkzeug `ProxyFix`, so the frontend
proxy must set `X-Forwarded-For` and `X-Forwarded-Proto`. The configured hop
count assumes nginx is the only trusted proxy directly in front of Gunicorn. If
a load balancer or another proxy is inserted before nginx, review the
`ProxyFix` hop count and nginx header handling before enabling the deployment.
Do not expose Gunicorn directly to untrusted clients, because forwarded headers
are trusted only under the single-nginx deployment model.

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
Environment=BASE_PATH=<result-data-root>
ExecStart=<venv>/bin/gunicorn \
  -w 2 \
  -b 127.0.0.1:8800 \
  --timeout 60 \
  --max-requests 1000 \
  benchkit.result_server.app:app
```

An equivalent direct import form is:

```text
BASE_PATH=<result-data-root> \
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

`BASE_PATH` is required because the application validates the result-data root
when `app.py` is imported. Point it at the directory that contains the portal's
received results, estimated results, profiler archives, and related runtime
data.

For deployments that want a separate audit file in addition to stderr capture,
set:

```text
RESULT_SERVER_AUDIT_LOG_FILE=/path/to/audit.jsonl
```

The service user must be able to append to that file. Keep rotation and access
controls in the systemd/logrotate or log aggregation layer.
