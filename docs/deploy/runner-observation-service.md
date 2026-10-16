# Standalone Observation Receiver

Use a stable observation receiver and an independent Collector when the shared
observation store must outlive a development Portal checkout. Installing code
does not enable the API, change existing collection or authorize a shared-store
cutover. Start with the [isolated acceptance checklist](../runner-observation-isolated-acceptance.md).

## Deployment Units

- Receiver: a selected immutable release, compatible Python 3.12+ environment,
  dedicated configuration, TLS certificate/key and an existing SQLCipher store.
  Use the existing server requirements and optional encrypted-DB requirements.
  No package acquisition or environment creation happens at application startup.
- Collector: its own selected release, Python 3.12+, explicit private JSON
  configuration, delivery credential, GitLab read-only credential references
  and private delivery state. Its runtime uses the standard library; it does not
  need the receiver's Flask, Redis client, SQLCipher or Web environment.
- Redis: provision a Unix socket explicitly and choose a separate rate-limit
  namespace. The receiver never falls back to the Portal's Redis URL/namespace.
  Separate namespaces do not provide physical isolation; use a dedicated backend
  for acceptance when an existing backend must not be affected.

Record release revisions as provenance. Do not require Collector and receiver
to share a revision when their protocol and behavior are compatible. Installed
release copies are deployment artifacts, not separately edited source trees.

## Receiver Configuration and Startup

Examples are in [deploy/runner-observations](../../deploy/runner-observations/).
They are inert templates, not installers. Review all paths, bind port, target
identities, generation, credential digest, schedule and service names before
creating any deployment files. Replace every `/example` path and sample identity.
The example port is not reserved or checked for availability by the templates.

The receiver uses only these settings:

| Setting | Meaning |
| --- | --- |
| `RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED` | Must be explicitly true for this standalone process |
| `RESULT_SERVER_RUNNER_OBSERVATION_PREFIX` | Optional route prefix; no trailing slash or URL/query components |
| `RESULT_SERVER_RUNNER_OBSERVATION_BIND` | Explicit `127.0.0.1:<port>` listener; wildcard/hostname binds are rejected |
| `RESULT_SERVER_RUNNER_OBSERVATION_TLS_CERT_FILE` / `TLS_KEY_FILE` | Absolute certificate/private-key references for Gunicorn |
| `RESULT_SERVER_RUNNER_OBSERVATION_REDIS_SOCKET` / `REDIS_PREFIX` | Explicit absolute Redis Unix socket and namespace ending in `:` |
| `RESULT_SERVER_RUNNER_MONITOR_DB_PATH` / `KEY_FILE` | Absolute existing encrypted store and key in separate directories |
| `RESULT_SERVER_GITLAB_TARGETS` | Target identity catalog, without GitLab credentials |
| `RESULT_SERVER_RUNNER_OBSERVATION_SOURCES` | Dedicated credential digests and complete allowed collector/source/generation/target scope |

The TLS and Redis short names in the table use the same
`RESULT_SERVER_RUNNER_OBSERVATION_` prefix. The store's key-file setting is
`RESULT_SERVER_RUNNER_MONITOR_KEY_FILE`. Do not load a Portal environment file or
copy its session secrets, pipeline tokens, general ingest credentials or
submission grants. Use a new dedicated delivery credential, not an existing
Result API key; the receiver holds its SHA-256, not the delivery credential.

Keep configuration/key/state directories private and credential files mode 600.
Give only the receiver access to the observation DB/key; the Collector needs
neither. Provision the store and keys separately after approval using the existing
explicit lifecycle tools. The factory does not create a database, migrate a schema,
read an encryption key or connect to Redis during startup. Syntactic configuration
validation is not proof that referenced files, certificates or Redis are usable.
Verify permissions, integrity and recovery on isolated fixtures first.

From the release's `result_server` directory, select the compatible receiver
environment and use the same settings for Gunicorn and the WSGI factory:

```text
<receiver-venv>/bin/gunicorn --config python:observation_gunicorn 'observation_app:create_app()'
```

This is an observation-only app: no Portal factory, static files, Profile/Result
initialization, browser sessions or triggers. It registers only the existing
observation API and dedicated authentication. It rejects cleartext HTTP, does
not trust forwarded-scheme headers, and accepts no browser/proxy/Result-key
authentication fallback. Gunicorn binds loopback with TLS, disables access logs
and forwarded-scheme interpretation, and uses bounded worker/graceful timeouts.
Do not add payloads, authorization headers or key values to operational logs.

Scope and replay protections are the same as the [protocol](../runner-observation-protocol.md).
Invalid standalone configuration prevents factory startup with a fixed error.
Missing/wrong/uninitialized storage or unavailable required Redis refuses
requests without initializing storage or treating delivery as acknowledged.

## Collector and Scheduling

Use the existing [Collector CLI](../runner-observation-protocol.md) with an
absolute private configuration path. Set the endpoint to the receiver's exact
HTTPS prefix plus `/api/v1/runner-observations`. If using a deployment-specific
CA, expose `SSL_CERT_FILE` only to the Collector process; do not disable TLS
verification or change the machine-wide trust store.

State initialization remains a separate approved operation. The service template
only calls `collect`; it cannot initialize/reset state or change generation.
Name the installed service `benchkit-runner-collector.service` when using the
example timer, or adjust the timer's `Unit` consistently. Its five-minute interval
is an example, not a request to change an existing collection cadence. Review
stop/start timeouts against the existing collection and retry bounds.

Do not enable the new timer while a legacy direct-DB Collector owns the same
store. A newly enabled timer may collect immediately. Creation of credentials,
services, timers, listeners, actual GitLab requests and cleanup require explicit
deployment approval; these files do none of that automatically.

## Cutover and Return

First validate the permanent startup entry against a dedicated test DB,
credential, Redis and fixture observations. Check TLS, authentication, rejected
requests, acknowledged state, retained observations, and the resolved paths. The
existing synthetic factory/Gunicorn tests do not prove systemd permissions, real
certificate trust or live isolation on a particular deployment.

For shared collection, stop the old timer, finish/drain writers and take a fresh
consistent encrypted backup. Check source/target identities and the latest
cursor/state before enabling one new writer. Stop on an existing unexpected
cursor or ownership conflict; no administrative retirement/reset command is
provided here. Confirm natural collection before changing a development Portal.
Changing the shared store can affect every Portal reading it even without a Web
restart; it is not an isolated development-only change.

Before the first API write, verify unchanged storage/state before returning to
the old writer. After any accepted write, keep the newest observations: stop and
drain the new writer/receiver, archive the latest encrypted snapshot/cursor and
pending state, and reconcile acknowledgements before returning. Never blindly
restore a pre-cutover DB. A legacy writer drops API cursor metadata, so a later
return to the API needs a reviewed new generation/state and retired authorization.
See the [handoff procedure](../runner-observation-handoff.md) for the full boundary.

Remove only explicitly approved temporary resources after acceptance. Retain
private operational backups according to the deployment's recovery policy;
do not delete them merely because a release reference was switched.
