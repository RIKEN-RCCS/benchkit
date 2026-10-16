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
Trial it with fixtures, then development previews, then integration verification,
before approving a production switch. Check session/authentication
continuity and submission permissions before changing an existing service.

Prepare code and a compatible venv as one deployment unit. Do not update a venv
in place while other instances still use it. A shared Runner collector should
use an explicitly selected stable deployment rather than a mutable preview.
The opt-in examples below do not provision or switch deployment references.

Treat shared Budget/Runner schema changes separately from instance deployment.
Resolve backup and backward compatibility before reverting code; do not restore
an old DB over newer writes as part of an ordinary rollback.

## Opt-In Service Layout

`deploy/instances/` contains user-service examples, not an installer. Existing
units, environment files, checkouts, timers, and data are unchanged until an
operator explicitly deploys a reviewed configuration. Do not enable a second
trigger timer alongside the existing one.

Each instance has one selected deployment pair:

```text
~/.local/lib/benchkit/cx/<instance>/
  deployments/<selected>/
    code -> <selected checkout or release>
    venv -> <compatible completed venv>
  current -> deployments/<selected>
```

All three services use `current/code/result_server` as their working directory
and executables under `current/venv/bin`. The preview checkout can stay in its
existing location. The reference is a deployment selection, not a second code
source or an instruction to update the checkout. Preserve its Version Check
repository/ref settings. Do not change the pair while a trigger invocation is
running; stop its timer, wait for completion, and stop both Web surfaces before
changing the pair. Start the selected surfaces after the approved switch.
Updating a venv in place is not part of this layout.

The required files under `~/.config/benchkit/cx/<instance>/` are read by systemd,
in the following order. No application-side env parser is added.

| File | Public | Console | Trigger | Contents |
| --- | --- | --- | --- | --- |
| `connections.env` | yes | yes | yes | Deliberately shared DB/key-file references and common connection settings |
| `instance.env` | yes | yes | yes | Instance identity, data directory, public URL, namespace and cookie identity |
| `web.env` | yes | yes | no | Existing Web credentials/authentication settings |
| `public.env` | yes | no | no | Public bind address and worker count |
| `console.env` | no | yes | no | Console bind/workers and already authorized Console-only settings |
| `trigger.env` | no | no | yes | Explicit evaluation mode and separately authorized scheduled-submission settings |

The common files are shared between roles of one instance, not automatically
between all instances. Keep identity, keys, grants, and benchmark storage
separate. References in `connections.env` are not a reason to grant new DB
access to a role; review that access before consolidation. If access differs,
keep the relevant reference in the authorized role file instead. Web-only
secrets must not be copied to the trigger, and Console grants must not be copied
to public or scheduled submission. Missing required files fail startup rather
than falling back to another instance. Keep configuration directories private
and files mode 600.
These user services still share one OS account; separate env files are not
OS-level privilege isolation.

Public and Console explicitly call `create_instance_app('public')` and
`create_instance_app('console')`; stale public-mode flags do not select the
surface. Set `BENCHKIT_WEB_BIND` and `BENCHKIT_WEB_WORKERS` in the matching role
file. Bind to loopback behind the intended proxy. The example ports are only
examples; retain deployed ports and proxy restrictions during a configuration
migration. Preserve the effective TOTP issuer, cookie name, signing secret,
storage paths, grants, and URL prefixes, not merely the spelling of old env
variables. The factory adds the development suffix to `TOTP_ISSUER`.

The trigger omits `--db` and `--result-server-url`, resolving the same instance
DB and `RESULT_SERVER_PUBLIC_URL` instead. Its example defaults to `--dry-run`;
set `BENCHKIT_TRIGGER_MODE=--submit` only for an explicitly approved submission
service. Preserve existing lock, observation-recording, lookback, and schedule
behavior. Dry-run still evaluates and may write DB records or locks; it is not
a read-only check and must not be run against live storage just for validation.

Before enabling these examples, stop the previous timer and wait for its
invocation to finish, take the required private configuration/data checkpoint,
and verify the selected deployment with fixture storage. Keep old unit/env
definitions for rollback, but never run old and new schedulers concurrently.
After acceptance, enable exactly one scheduler. Reverting a compatible
configuration means restoring references and the intended unit state, not
restoring an old DB over newer writes. DB/schema migrations require their own
backup and compatibility procedure. The independent observation Collector and
receiver are outside this instance switch and must not be redeployed with it.
