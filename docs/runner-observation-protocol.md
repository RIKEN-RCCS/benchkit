# Runner Observation Protocol Core

The protocol has a pure core and an experimental, opt-in CX receiver. The
receiver is disabled by default; existing collection and credentials remain
unchanged. Collector delivery components are available separately; wiring the
existing collection command to them remains future work. See
[current monitoring](guides/runner-monitoring.md) for the existing
operational interface.

## Entry Points

`result_server/utils/runner_observation_protocol.py` uses only the Python standard
library. It does not import the web application, GitLab client or SQLCipher.

- `TargetSpec` defines a target ID, stable server ID, canonical HTTPS server URL,
  project and permitted runner types.
- `SourcePolicy` defines the collector/source IDs, active generation UUID and
  complete set of targets. The receiver supplies this from authenticated
  configuration, never from the observation body.
- `validate_batch(raw, policy, received_at=...)` validates UTF-8 JSON bytes and
  returns normalized data. `received_at` must be an explicit UTC datetime.
- `apply_batch(previous, raw, policy, received_at=...)` returns `BatchUpdate` with
  a new snapshot, acknowledgement and `changed` flag. Neither input is modified.
- `ProtocolError` contains only a fixed code and proposed HTTP status, not
  rejected values. No HTTP responses are sent by this module.

## Version 1 Batch

The envelope requires exactly `schema_version` (integer 1), `collector_id`,
`source_id`, `generation`, `sequence`, `batch_id`, `started_at`, `finished_at`,
`targets` and `runners`. Unknown fields and versions, duplicate JSON keys and
non-finite JSON constants are rejected. IDs are bounded ASCII identifiers;
numeric IDs and sequence must be integers in `[1, 2^53-1]`, not booleans.

The generation must match policy. `batch_id` is UUIDv5 with the generation UUID
as namespace and the unpadded decimal sequence as name. The policy's full target
set must appear exactly once. Each target contains `target_id` and `inventory`.
Each runner contains `server_id`, `runner_id`, `detail` and `managers`, exactly
once per server/runner pair found in successful inventories. Failed inventories
do not submit their previous data.

Every resource contains `status` and `observed_at`, plus either `data` for `ok`
or a fixed `error_code` for `error`, never both. An `ok` inventory or manager list
is complete, possibly empty. Partial pagination is an error, not a successful
partial inventory. Summary, detail and manager fields are explicitly allowlisted
in the module; raw GitLab responses and arbitrary metadata are not accepted.
Unknown string heartbeats become `unknown`. Timestamps must be UTC, and resource
observation times must fall within the batch interval. Arrival more than five
minutes before batch completion is rejected; delayed observations remain old.

Bounds are 4 MiB per JSON body, 100 targets, 10,000 unique runners, 10,000
managers across the batch, 2,048 characters per text field and 1,000 tags per
runner. These safety bounds are not an operational capacity guarantee.

## State and Replay

Successful resources replace their data and success timestamp. Failed resources
retain preceding data/success timestamps and update only attempt/error state.
Complete successful inventories replace project membership; failed inventories
retain it. Runners shared across projects are deduplicated by server URL and ID.
A runner disappears from the active snapshot only after all retained membership
is gone. Nothing changes Budget, execution routes or trigger permissions.

The output preserves the existing `targets`/`runners` presentation shape and adds
`_ingest` cursors containing sequence, batch ID, normalized-content SHA-256,
initial receipt time, collector/generation and historical target identities.
These identities bind the cursor to its scope; they are not configuration.
Different sources may not own overlapping targets or servers. Scope/generation
changes need an explicit administrative handoff, not implicit reset.

Same sequence and content returns `changed=False` and a `duplicate`
acknowledgement with the original receipt time. Lower sequences and conflicting
same-sequence content are rejected; gaps are allowed. JSON object key order and
equivalent UTC timestamp spelling do not create a conflict. Receipt time does
not refresh observation freshness. The content digest is not authentication.
Corrupt cursor state is an error, never a fresh starting sequence.

The receiver reloads the latest snapshot inside a writer transaction, calls this
core, then commits snapshot and cursor together. Do not enable this alongside a
legacy direct-DB writer, which does not preserve these cursors. The pure module
itself does not perform authentication, HTTP handling or persistence.

## Opt-In CX Receiver

The dedicated receiver accepts `POST /api/v1/runner-observations` below the
configured console prefix. It is not registered on public portals or unless
`RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED=true` (or `1`). It uses a
separate blueprint and `collector_api` access class, not the general Result API.
Only this machine endpoint is additionally exempted from CSRF; browser routes
remain protected.

`RESULT_SERVER_RUNNER_OBSERVATION_SOURCES` is a JSON object of permitted sources:

```json
{
  "example-source": {
    "collector_id": "example-collector",
    "generation": "11111111-1111-4111-8111-111111111111",
    "key_sha256": "<64 lowercase hexadecimal SHA-256 characters>",
    "targets": [{"target_id": "example", "server_id": "example-server"}]
  }
}
```

The verifier is a placeholder, not a usable credential. Generate a high-entropy
random, URL-safe ASCII key (32 to 256 characters), not a human password. Keep the
plaintext key only with the collector and send it in `X-Collector-Key` over
HTTPS. CX stores its lowercase SHA-256 verifier and uses constant-time digest
comparison. This credential is independent of the observation database's
encryption key. Do not log keys or include them in URLs or command arguments.

Target IDs refer to the existing `RESULT_SERVER_GITLAB_TARGETS` catalog, for
example `example=gitlab.example.org/group/project`. Server URLs and projects are
resolved there, not repeated in the source configuration or trusted from the
request body. Each target may also specify `runner_types`. Duplicate source
verifiers, reuse of a configured Result API key and overlapping target/server
ownership are rejected. Invalid active configuration returns a generic 503,
with no fallback to other credentials.

The receiver does not accept `X-API-Key`, trusted-proxy headers or browser
sessions instead of its dedicated key; observation keys are not Result API keys.
It does not fetch GitLab or authorize executions. After authentication, the
existing namespace-scoped rate limiter applies (20 requests/minute per source
by default). Required Redis failures return 503. Body size is bounded even
without Content-Length; compressed bodies are not accepted. Responses use
`Cache-Control: no-store` and fixed error codes, not upstream bodies or paths.

The receiver uses the configured observation DB/key references from
`RESULT_SERVER_RUNNER_MONITOR_DB_PATH` and
`RESULT_SERVER_RUNNER_MONITOR_KEY_FILE`. Registration never opens or creates
these files. Initialize storage through the existing explicit lifecycle only.
Requests use `BEGIN IMMEDIATE`, read the latest state, apply the core and commit
one encrypted snapshot row containing both data and cursor. Rejected requests
and failed transactions do not advance the cursor. Duplicate delivery does not
issue an UPDATE. Existing schema-1 readers can read the additional metadata;
no automatic schema migration is performed.

Activation requires stopping the legacy direct-DB collector, a current encrypted
backup and a tested handoff/rollback plan. New writes make unconditional restore
of an older backup unsafe. Use a separate store and credential for trials, never
an observation DB shared with production. Merely deploying code does not enable
this endpoint, and these tests do not constitute deployment acceptance.

## Collector Delivery Components

`result_server/collector/` is a separate, standard-library-only delivery package.
Its sole CX-side code dependency is the pure observation protocol contract. It
does not import Flask, Redis, SQLCipher, the application factory or the GitLab
client, and never loads runtime environment settings. It is a component API,
not a replacement for the existing collection command or a new scheduled job.

- Construct a `SourcePolicy` and an `HTTPSDelivery(endpoint, key_file)` explicitly.
  The endpoint must be the exact HTTPS observation API URL, including any console
  prefix. It is never inferred from a Result Server default. Credentials, query
  strings, fragments and path traversal are not allowed in the endpoint.
- Create a dedicated private state directory (owner-only mode 700), then call
  `DeliveryState(directory, policy, endpoint).initialize()` once. Initialization
  never overwrites existing state. Missing or corrupt state on a later run stops
  delivery; it does not restart the sequence or generate a new generation.
- Call `run_once(directory, policy, transport, collect)` explicitly. The injected
  `collect(sequence)` producer returns complete JSON bytes conforming to the
  shared protocol. `batch_identity(policy, sequence)` supplies common envelope
  fields without maintaining a second identity definition. Collection wiring
  and GitLab credential configuration are not implemented by this API.
- State binds the endpoint, collector/source/generation and full target scope.
  Endpoint or scope changes require an explicit handoff, not silent reuse. A
  separate state directory is required for each source/destination combination.

The state directory holds `delivery.json` and `delivery.lock`, both mode 600.
Directory/file ownership, canonical paths, symlinks and file hardlinks are
checked. A nonblocking process lock covers loading, collection, delivery and
acknowledgement. A same-directory temporary file is flushed and fsynced before
atomic publication, followed by directory fsync. No CX DB or encryption key is
needed. The local spool contains potentially sensitive observations in plaintext;
keep it private and do not put it in a source checkout or logs. It contains no
delivery credential.

One pending batch is saved durably **before** sending. When pending state exists,
the next invocation resends those exact bytes and does not collect another batch,
even if the replay succeeds. Sequence advances and pending state is cleared only
after a matching `200 accepted` or `200 duplicate` acknowledgement. The source,
generation, sequence, batch ID, schema and UTC receipt timestamp are checked;
arbitrary 2xx responses, malformed acknowledgements and mismatches do not clear
state. An accepted request followed by a lost response or local-save failure is
therefore replayed through CX's duplicate contract. It never refreshes observed
timestamps. Sequence exhaustion requires administrative attention, not wraparound.

The plaintext delivery key is read only from an explicitly supplied private
file (parent 700/file 600), never an argument containing the key itself. HTTPS
uses certificate/hostname verification, rejects redirects and disables ambient
proxy discovery. Only `X-Collector-Key` is sent; there is no alternate API-key,
session or proxy-authentication fallback. Responses are bounded to 64 KiB, and
compressed responses are rejected. Diagnostics are fixed codes, not HTTP bodies,
credentials or filesystem paths.

Connection failures and HTTP 429/500/502/503/504 may retry the same pending batch.
There are at most three attempts, with a monotonic 60-second retry budget and
per-attempt I/O timeout of at most 20 seconds. Retry-After (seconds or HTTP date)
is honored only within the remaining budget; otherwise the batch stays pending
for a later invocation. These are retry/I/O budgets, not a process watchdog for
DNS resolution or a continuously trickling peer. Certificate failures, redirects,
other status codes and invalid acknowledgements stop without changing pending
content, generation or sequence. Scheduling and service-level timeouts remain
explicit deployment concerns.

These components do not enable the CX receiver, fetch GitLab, schedule a timer,
modify existing collection, or perform a handoff/rollback. Validate the producer
adapter and generation/cursor handoff separately before a deployment trial.

## Synthetic Tests

```bash
python -B -m pytest -q -p no:cacheprovider result_server/tests/test_runner_observation_protocol.py
```

Tests use in-memory JSON and synthetic snapshots, explicit clocks and dummy
identities. They exercise partial failures, recovery, empty inventories,
multi-project identity, independent sources, replay/order, malformed data,
bounds and corrupt cursors. I/O guards check the pure operations, and an import
test rejects dependencies on CX modules, Flask or SQLCipher. No configuration,
credential, live database, network service or deployed application is required.

`test_runner_observation_ingest.py` tests authentication, CSRF isolation, public
and disabled surfaces, bounded bodies and rate limiting with a fake store and
fake Redis. `test_runner_observation_ingest_storage.py` additionally requires
the optional SQLCipher dependency and uses synthetic keys and temporary DBs for
round trips, duplicate delivery, rollback, competing writers and latest-cursor
checks. Missing SQLCipher is a skip locally, not successful encryption coverage;
the encrypted CI job requires the driver and runs these cases explicitly.

`test_runner_observation_delivery.py` uses synthetic private state/key files,
fake HTTP and clocks, and a guard rejecting real socket connections. It covers
durable-before-send ordering, replay after response/ack-save loss, process locks,
corrupt state, permission/symlink/hardlink rejection, scope binding, bounded
retries and protocol-compatible duplicate acknowledgements. Isolated import
checks run without site packages and reject web/database dependencies. TLS and
redirect handling are checked with fake openers, not live HTTPS connections.
