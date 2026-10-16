# Instance Configuration and Startup

Use the same startup mechanism for three distinct roles:

| Repository source | Instance | Purpose | Public / Console prefix |
| --- | --- | --- | --- |
| Approved release from `main` | `main` | Production | `/` / `/console` |
| Selected `develop` revision | `dev1` | Integration verification | `/dev` / `/dev/console` |
| Selected `feature/*` revision | `dev2` | Development preview | `/dev2` / `/dev2/console` |

Repository updates do not automatically deploy to production. Keep the deployed
production revision independent of subsequent `main` updates. Development
previews do not need to use the same revision as integration verification.

## One Instance Definition

The opt-in `create_instance_app` factory and trigger runner use
`utils/instance_config.py`. It resolves references without opening databases,
creating directories, or modifying environment variables.

Set `RESULT_SERVER_INSTANCE` explicitly to `main`, `dev1`, or `dev2`, and either:

- Set `BASE_PATH` to an absolute root containing the instance directories; or
- Set `RESULT_SERVER_DATA_DIR` to that instance's absolute data directory.

The explicit data directory takes precedence. Existing data need not move.

| Reference | Default | Existing override |
| --- | --- | --- |
| Profile and metadata-index DB | `<data-dir>/cx_portal.sqlite3` | `RESULT_SERVER_DB_PATH` |
| Redis namespace | `main:`, `dev:`, `dev2:` | `RESULT_SERVER_REDIS_PREFIX` |
| Session cookie name | `session_main`, `session_dev`, `session_dev2` | `RESULT_SERVER_SESSION_COOKIE_NAME` |

Result, Estimate, artifact, and filesystem-session directories remain under the
instance's data directory. A separate Profile DB is supported by the override;
do not merge benchmark storage merely to standardize startup. The new resolver
requires absolute storage paths and does not default an unspecified instance
to production.

Keep environment loading in the service manager, not a second application-side
env-file parser. Load common connection references, then one instance-specific
environment file into both Web services and the trigger runner. Keep instance
identity, storage, secrets, public URL, and submission grants out of the common
file. Budget and Runner DB/key-file references may be shared deliberately;
sharing them does not merge the instance-local data. Do not broaden credential
distribution when consolidating files.

## Startup Entrypoints

Use the same code revision and compatible venv for an instance's public Web,
Console, and trigger runner. Put `result_server` on `PYTHONPATH` and use these
entrypoints from that directory:

```text
<venv>/bin/gunicorn 'app:create_instance_app("public")'
<venv>/bin/gunicorn 'app:create_instance_app("console")'
<venv>/bin/python -m trigger_runner --dry-run
```

Bind addresses, workers, logs, and reverse-proxy access restrictions remain
service-manager settings. Public and Console services differ in their explicit
surface and bind address, not in their instance definition. The public factory
enforces public mode even if a stale environment flag says otherwise; the
Console factory retains authenticated management routes. This is not a
replacement for the proxy restrictions or application authorization.

The trigger runner reads the same Profile DB reference when `--db` is omitted.
An explicit `--db` remains supported for existing services and offline copies.
Submission still requires `--submit`; retain `RESULT_SERVER_PUBLIC_URL` or an
explicit `--result-server-url` for the intended destination. Do not start a
submission service just to check its configuration.
`--dry-run` prevents submission but is not a read-only DB inspection: evaluation
can record run status and acquire locks. Use temporary fixture storage for
startup tests, not a production DB.

Legacy `app:app`, `app:app_dev`, and `app:create_app(...)` entrypoints remain
available. Legacy `app`/`app_dev` require `BASE_PATH` and initialize only the
requested application; merely importing the module no longer creates both.
Secret preflight still runs before each application's initialization. The
explicit factory does not require `BASE_PATH` when a data directory is supplied.

## Deployment Boundaries

This interface does not rewrite existing units, move data, or migrate schemas.
Trial it with fixtures, then integration verification, then development
previews, before approving a production switch. Check session/authentication
continuity and submission permissions before changing an existing service.

Prepare code and a compatible venv as one deployment unit. Do not update a venv
in place while other instances still use it. A shared Runner collector should
use an explicitly selected stable deployment rather than a mutable preview.
Service templates and release-reference switching can follow once the startup
interface has been validated; they are not provisioned by this factory.

Treat shared Budget/Runner schema changes separately from instance deployment.
Resolve backup and backward compatibility before reverting code; do not restore
an old DB over newer writes as part of an ordinary rollback.
