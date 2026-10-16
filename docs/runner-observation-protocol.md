# Runner Observation Protocol Core

This is an experimental, storage-free core, not an enabled HTTP API. Existing
collection, credentials, encrypted storage and console routes are unchanged.
Transport, authentication, local delivery state and persistence are separate
future work. See [current monitoring](guides/runner-monitoring.md) for the
operational interface.

## Entry Points

`result_server/utils/runner_observation_protocol.py` uses only the Python standard
library. It does not import the web application, GitLab client or SQLCipher.

- `TargetSpec` defines a target ID, stable server ID, canonical HTTPS server URL,
  project and permitted runner types.
- `SourcePolicy` defines the collector/source IDs, active generation UUID and
  complete set of targets. A future receiver must supply this from authenticated
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

A future receiver must reload the latest snapshot inside a writer transaction,
call this core, then commit snapshot and cursor together. Do not enable this
alongside a legacy direct-DB writer, which does not preserve these cursors.
Atomic persistence, encryption, concurrency, authentication and HTTP isolation
are **not** provided or validated by this pure module.

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
