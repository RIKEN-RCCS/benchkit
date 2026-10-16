# Runner Observation Handoff Rehearsal

This procedure describes a **copy-only rehearsal**, not a deployment command.
The tests generate synthetic keys, a legacy-shaped encrypted observation DB and
Collector state, then operate only on private copies. They neither read a deployed
configuration/key/DB nor contact GitLab or CX. No administrative cursor-reset,
restore or service-switch command is added.

See the [protocol and Collector CLI](runner-observation-protocol.md). Enabling a
receiver, provisioning credentials and changing running writers require a
separately reviewed, deployment-specific plan.

## Freeze and Backup Boundary

Before a real change, identify the single writer for each observation store and
source. Stop the old Collector and any competing writer, drain in-flight delivery,
and keep the new receiver disabled. Do not assume a file lock alone prevents old
and new writers from interfering: the legacy writer does not preserve API cursors.

While writers are stopped, take a consistent encrypted DB backup using the existing
backup API. If delivery state exists, lock and copy its state at the same frozen
boundary. Keep configuration references and generation/scope identities with the
checkpoint, not credential values. Check encrypted integrity and compare decoded
observations and cursors on a private copy. Keep key custody independent of DB
backup custody. Local Collector state contains private plaintext observations.

If data, cursor, ownership, generation or pending delivery changes after this
checkpoint, stop and take a new checkpoint. The rehearsals do not establish that
any particular live writer is stopped or that a deployed backup pair is coherent.

## Initial Legacy to API Switch

The legacy snapshot has `targets` and `runners` but no `_ingest` cursor. A new,
explicitly configured generation and fresh Collector state start at sequence 1.
Keep existing observations in the copied DB; do not initialize an empty DB in
their place. The first accepted batch adds its cursor. Failed resources retain
previous successes and original success timestamps while recording the failure;
failed inventories do not erase retained membership. Repeated delivery does not
make old observations fresh. Complete empty successful inventories are different
from unavailable inventories and may legitimately remove membership.

Only after the copy rehearsal and deployment approval should the scoped receiver
and one new Collector become active. The existing CLI/timer is not automatically
replaced by installing the code.

## Continuing an Existing Generation

Move the encrypted snapshot/cursor and Collector state as a matched checkpoint.
Keep endpoint, source/collector IDs, generation and complete target scope unchanged.
Do not reset sequence or edit a pending batch during relocation.

| Frozen pair | Required interpretation |
| --- | --- |
| No pending batch; next sequence is CX cursor + 1 | Normal continuation when the pair and identities are confirmed |
| Pending sequence equals CX cursor | Rehearse the same bytes; only a matching duplicate acknowledgement permits clearing pending state |
| Pending sequence is CX cursor + 1 | Unacknowledged delivery can be rehearsed against the matching prior DB snapshot |
| Pending sequence is older, conflicts at the same sequence, or belongs to another scope/generation | Stop; retain both copies and reconcile, never silently renumber |
| Collector has acknowledged data absent from an older DB copy | Stop; a sequence gap being legal does not recover missing acknowledged observations |

The tests show that one pending batch can catch up a matching pre-acceptance DB
copy, and that stale/conflicting pending content is rejected without changing
either state. They do not implement a general backup-pair reconciliation tool or
claim that all pairs satisfying a numeric relationship are safe.

## Changing Generation or Ownership

Changing receiver configuration alone is intentionally insufficient when the DB
already contains another generation's cursor. It returns 409 and leaves the DB
unchanged. A Collector also refuses state bound to a different generation/scope.

The rehearsal simulates an explicit administrative edit on an isolated copy:

1. Freeze writers and archive the full encrypted snapshot/cursor and pending state.
2. Resolve pending deliveries before retiring their generation; do not discard
   unacknowledged observations merely to unblock a new generation.
3. Verify the current snapshot still equals the reviewed checkpoint. Preserve all
   observations and other sources' cursors. Retire only the selected source's old
   cursor in the copy; do not fabricate a digest or rewrite it as a new generation.
4. Configure the new generation/scope and a separate fresh Collector state.
   Old-generation requests must fail before any write. Where credentials or
   ownership change, revoke the former delivery authorization as part of the
   reviewed control-plane change.
5. Rehearse the first new-generation batch and integrity check. Unchanged target
   identities keep prior successes; changed identities must not inherit old project
   membership. Confirm unrelated sources remain unchanged.

The cursor edit exists only inside a test fixture. There is **no supported live
reset command** in this change. A real transition still needs an explicit,
transactional administrative operation with checkpoint checks and audit/backup
retention; the test must not be copied into a live DB-edit script.

## Returning to Legacy Collection

Before the first new write, returning to the previous configuration can use the
unchanged observation DB, after confirming snapshot/cursor and delivery state
have not changed. Do not restore a backup just because it predates the switch.

After any API acceptance, the earlier backup is stale. Stop the new Collector,
disable its receiver/authorization and drain in-flight work; freeze and back up
the **latest** DB plus Collector state. Keep current observations when resuming
legacy collection rather than replacing them with the earlier backup. The tests
verify that disabling the receiver rejects later delivery and that the legacy
collection function can consume the current snapshot. The entire previous
deployed application and service configuration are not exercised here.

The legacy writer replaces the snapshot and drops `_ingest` metadata. Archive the
pre-return cursor and pending state before allowing it to write. If API delivery
is enabled again later, use a separately reviewed **new generation and fresh
state**, not an old pending batch/cursor or still-valid retired authorization.
Otherwise replay protection could be lost. Keep the old API disabled while the
legacy writer owns the store; do not operate both concurrently.

## Verification Scope

`test_runner_observation_handoff.py` uses SQLCipher-required temporary DBs and
fake transports/Flask test clients. Each scenario compares the synthetic source
DB's decoded state and encrypted bytes before/after to prove it was not modified.
The tests check backup integrity, initial failure preservation, paired relocation,
duplicate/stale/conflicting replay, mismatched checkpoint history, generation
refusal, a copy-only epoch transition, other-source retention and safe return
conditions. Real configuration, keys, original DBs and services are untouched.
