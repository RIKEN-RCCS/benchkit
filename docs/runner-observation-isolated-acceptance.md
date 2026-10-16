# Isolated Runner Observation Acceptance

This is a preparation and approval checklist, not an instruction to change a
running instance. Begin with synthetic data and fake transports. Do not use an
existing shared observation store, deployed credentials or a scheduled Collector
for this acceptance exercise. See the [copy-only handoff rehearsal](runner-observation-handoff.md).

## Administrative Safety Review

Prefer a new isolated store and a new generation for the initial acceptance.
There is no need to retire a live cursor, move existing state or change ownership
to test this path. The existing `init`, `check` and `backup` operations do not
implement a guarded cursor transition or prove that competing writers are stopped.

Before proposing any real state/ownership transition, record these requirements:

| Boundary | Evidence required before a write | Stop condition |
| --- | --- | --- |
| Authorization | Approved instance, source, operation, generation and complete target scope | Missing approval, unknown source or scope mismatch |
| Single writer | Old scheduler/Collector and receiver writers stopped and in-flight work drained | An unknown, active or newly started competing writer |
| Storage identity | Reviewed canonical paths, private ownership/modes, no symlink/hardlink or shared-store alias; DB identity and schema unchanged | Replaced file, changed identity/schema or shared storage |
| Checkpoint | Consistent encrypted backup plus corresponding locked Collector state; integrity and copy recovery checked | Missing/stale backup, unresolved pending delivery or mismatched checkpoint pair |
| Transaction | Re-read and compare the reviewed snapshot/cursor inside the write transaction; modify only the approved source | Observation/cursor changed since review, unrelated-source modification or partial update |
| Completion | Integrity check, observation retention and exact intended cursor change; private value-free audit record | Failed check, unknown commit outcome or acknowledgement inconsistent with state |

A path check or file lock alone is not sufficient. An SQLite write transaction
serializes participating DB writers but does not stop a scheduler or a legacy
writer from writing immediately afterwards. Writer control and transaction checks
are both required. Backup identifiers/checkpoint identities belong in a private
operational record, not public logs; do not include key values or observation
payloads in that record.

**The guarded administrative transition is not implemented.** Do not turn the
test-only cursor edit into a DB repair command. Until a separately reviewed
operation enforces the checks above, a real cursor retirement/ownership change
remains blocked. Failed verification is not permission to reset sequence, remove
pending observations or restore an old DB.

## Isolation Plan for a Development Instance

Prepare the following manifest privately, using references rather than secret
values. Review it before creating or changing anything in a running deployment:

- Exact non-running code candidate, component/schema compatibility and proposed
  test lifetime. The commit records what was tested, not a requirement that all
  components share a commit.
- Separate test DB directory and test-only SQLCipher key directory, both private;
  verify canonical paths and inode identities do not alias any existing store/key.
  Prefer synthetic observations over a production DB copy for initial acceptance.
- Separate Collector configuration/state and delivery credential. The Collector
  receives no CX DB path, SQLCipher key or complete CX environment.
- A distinct Console endpoint/prefix and explicit allowed source/generation/target
  scope; no fallback to the production endpoint or shared Runner DB. Verify the
  resolved server-side store, not just the source name or URL label.
- Isolated Redis/rate-limit backend and isolated session/other writable storage
  when exercising a full application. A separate port alone does not isolate DB,
  Redis or background writers. Disable all timers, benchmark triggers and result
  forwarding in the test deployment.
- Local fixture collection first. Real GitLab GETs, network delivery, temporary
  listeners, credential creation, application startup and cleanup each need an
  explicit approval scope. Do not start an extra service as part of this document.

## Acceptance Matrix

| Exercise | Expected result |
| --- | --- |
| Collector `init` using explicit private configuration | State created; no collection or delivery; existing stores unchanged |
| Successful fixture inventory/detail/managers | Dedicated authenticated Console POST; snapshot and cursor persist together in the isolated encrypted store |
| Lost response after acceptance | Same pending bytes resent; duplicate acknowledgement; no second snapshot update or fresh collection |
| Wrong delivery key / source / generation | 401 / 403 / 409; no store update; pending state retained |
| Disabled or public receiver | 404; no store update; no alternate endpoint or authentication fallback |
| Missing receiving store configuration | 503; no DB auto-initialization; pending state retained after bounded retries |
| Next collection fails | Failure recorded without erasing prior success/timestamp; display marks observations unavailable rather than current |
| Dedicated credential separation | GitLab GET has no delivery key; CX POST has no GitLab token; logs contain neither |
| Exit and return | Stop only the approved isolated writer/listener; retain latest test checkpoint if needed; never restore it over an existing store |

The synthetic integration cases live in `test_runner_observation_handoff.py`,
already included in SQLCipher-required CI. They use real Collector configuration
loading, CLI, GitLab response parsing, delivery authentication, Flask routing and
encrypted persistence. Fake network openers bridge requests in process, with
socket connections forbidden. A conflicting synthetic CX environment points at
the untouched source fixture while the receiver is constrained to its test copy.
Every case verifies the source fixture's decoded snapshot and encrypted bytes are
unchanged. Rejected requests must not open the receiving store.

These tests do **not** prove live nginx/TLS routing, service isolation, firewall
rules, real Redis configuration, writer stoppage or deployment permissions.
Deployment acceptance must check those separately after approval. Record each
check as passed, failed or not verified; do not call the live cutover complete
based on synthetic tests alone.

## Approval and Return Boundary

Present the manifest, exact resources to create/change, outbound connections,
expected writes, retention and cleanup actions before isolated deployment.
Keep existing services/settings/DBs unchanged unless their individual change is
explicitly approved. Stop on an unexpected reference, competing writer or failed
check. Cleanup may remove only the named temporary resources after approval;
it must not remove a shared DB, retained backup or independent key backup.

For a later shared-store migration, submit a separate plan covering writer stop,
fresh backup, guarded transition, acceptance and restart. After any accepted API
write, keep the newest data: the pre-switch backup is not an unconditional
rollback target. Returning to legacy collection and re-enabling API collection
must follow the generation rules in the handoff rehearsal.
