# BenchKit Result Server Audit Log Specification

This document defines the structured audit events emitted by the BenchKit
result server. The audit log is intended for security monitoring and incident
review, not for storing secrets or full request payloads.

## Logger

- Logger name: `benchkit.audit`
- Format helper: `result_server/utils/audit_logging.py`
- Recommended formatter: `JsonAuditFormatter`
- Record shape: one JSON object per event
- Default destination: stderr, so systemd/Gunicorn deployments can capture it
  through `StandardError`
- Optional mirror destination: set `RESULT_SERVER_AUDIT_LOG_FILE=/path/to/audit.jsonl`
  to also append JSON Lines to a deployment-managed file

Common fields:

| Field | Meaning |
| --- | --- |
| `timestamp` | UTC ISO-8601 timestamp, added by the formatter |
| `level` | Python logging level |
| `event_type` | Stable event name |
| `actor` | Authenticated user email or runner id, when available |
| `target` | User, file, directory, or object affected by the event |
| `result` | `success`, `failure`, or `degraded` |
| `endpoint` | Flask route template, when emitted during a request |
| `method` | HTTP method, when emitted during a request |
| `ip` | Remote address as provided by Flask |
| `user_agent` | User-Agent header |
| `details` | Small structured context, with secrets redacted |

## Events

| Event | Result | Actor | Notes |
| --- | --- | --- | --- |
| `api_auth_success` | `success` | runner id | API key accepted. The key value is never logged. |
| `api_auth_failed` | `failure` | none | Missing or invalid API key. The presented key is never logged. |
| `ingest_accepted` | `success` | runner id | Result, estimate, PA data, or estimation-input upload accepted. |
| `api_query_accepted` | `success` | runner id | Authenticated API query accepted. |
| `rate_limit_exceeded` | `failure` | rate-limit key | Login, API, or admin fixed-window limit exceeded. |
| `redis_unavailable` | `failure` / `degraded` | none | Redis unavailable for authentication or throttling. |
| `login_success` | `success` | user email | User completed TOTP login. |
| `login_failure` | `failure` | user email, when known | Login failed. TOTP code is never logged. Invalid-code failures include a short-window failed-attempt count for audit context, but accounts are not hard-locked by that counter. |
| `setup_complete` | `success` | user email | Invitation-based TOTP setup completed. |
| `setup_failure` | `failure` | user email | TOTP setup verification failed. |
| `admin_user_invited` | `success` | admin email | Admin created an invitation. |
| `admin_user_deleted` | `success` | admin email | Admin deleted another user. |
| `admin_user_reinvited` | `success` | admin email | Admin reset TOTP via reinvitation. |
| `admin_affiliation_changed` | `success` | admin email | Admin changed another user's affiliations. |
| `admin_affiliation_rejected` | `failure` | admin email | Submitted affiliation value failed validation. |
| `admin_user_delete_blocked` | `failure` | admin email | Self-delete or only-admin delete was blocked. |
| `admin_affiliation_change_blocked` | `failure` | admin email | Removing the last admin role was blocked. |

## Data Handling Rules

Audit logs must not contain:

- API key values
- TOTP codes
- TOTP secrets
- Invitation tokens
- Flask secret keys
- Full request bodies or uploaded file contents

The audit helper redacts sensitive keys in `details`, including `api_key`,
`x-api-key`, `totp_code`, `secret`, `password`, and `token`. It records Flask
route templates instead of concrete request paths so route variables such as
invitation tokens are not copied into `endpoint`. Route code should still avoid
passing secrets to `audit_event()` in the first place.

## Retention Guidance

Recommended retention:

- Authentication and admin audit events: at least 1 year
- API ingest/query events: at least 3 months
- Debug application logs: deployment-specific, separate from audit logs

Production deployments should forward `benchkit.audit` logs to the site's log
aggregation system and restrict direct access to administrators.
