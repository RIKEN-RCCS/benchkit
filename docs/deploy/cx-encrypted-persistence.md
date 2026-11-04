# Encrypted Storage for Results, Profiles, Sign-In State and Artifacts

This is an opt-in storage backend, not an automatic deployment migration. The
default backend remains unchanged until an operator supplies both bindings.
Use the instance application factory, not the local stub-authentication app.

Here, CX persistence means the data retained by the portal between process
restarts: Result/Estimate documents and search facts, execution profiles and
submission history, users and sign-in sessions, and measurement/estimation files.
It does not mean a new benchmark execution engine or a Collector migration.

## Storage and Ownership

Each CX instance owns a pair of SQLCipher databases:

| Store | Contents | Commit boundary |
| --- | --- | --- |
| Metadata | Complete saved Result/Estimate bytes, hashes, query facts, visibility, Profile/approval/request/trigger history, users/TOTP/invitations, sessions, expiring security guards | Receipt bytes, facts and Profile metadata commit together before acknowledgement |
| Artifacts | Immutable generations of measurement archives, estimation bundles and retained inputs, in 1 MiB chunks | Commit a complete generation first, then atomically publish its references in metadata |

Large artifact writes do not hold the metadata writer lock. A failed publication
leaves the old references visible; completed but unpublished generations are not
served. Input archive replacement publishes all member references together.
Readers pin the selected generation, including during a concurrent replacement.

Budget and Runner observation databases keep their existing independent ownership
and keys. This backend does not migrate Collector delivery state, give Collector
CX database access, or change the observation API protocol.

JSON remains the API/export format. Import preserves original saved file bytes,
unknown fields, filenames, UUIDs, timestamps and scientific values. It does not
recover HTTP bytes that were never saved. Distinct filenames sharing a UUID are
not deduplicated. Unresolved references are not repaired by guessing.

## Configuration

Install the existing hash-pinned `requirements-budget-db.txt` in the candidate
environment in addition to `requirements-result-server.txt`. No new database
product or encryption implementation is required.

Set these bootstrap references in the separately managed instance environment:

```text
RESULT_SERVER_PERSISTENCE_DB=/srv/cx/example/private/cx.db
RESULT_SERVER_PERSISTENCE_KEY=/srv/cx/example/keys/cx.key
```

The artifact database defaults to `cx.db.artifacts`, beside the metadata DB.
`RESULT_SERVER_PERSISTENCE_ARTIFACT_DB` can explicitly select a different private
path. Keep both databases outside the logical document directories, and the key
outside both database directories. Reuse the established private-directory/file
requirements: directory mode 700, file mode 600, no symlinks or hard links.
Generate a fresh random key explicitly using the existing key helper. Never put
its value in configuration, logs, repository files or backup payloads.

The four logical roots correspond to `RECEIVED_DIR`, `ESTIMATED_DIR`,
`RECEIVED_MEASUREMENT_ARTIFACTS_DIR` and `RECEIVED_ESTIMATION_ARTIFACTS_DIR`.
They retain URL identities; encrypted mode does not write JSON or extracted files
there. An explicitly inventoried historical inputs directory can additionally be
bound with `RESULT_SERVER_LEGACY_INPUTS_DIR` and the `legacy_inputs` import role.
It is retained without guessing which current Result owns it.

App startup validates bindings, readiness, Profile schema and the artifact pair's
instance identifier. It never initializes, upgrades or rebuilds databases on GET.
Missing keys/drivers, unsafe files, wrong roots or incomplete imports fail closed.
There is no silent fallback to old JSON, plaintext Profile SQLite or Redis users.
Web, Console, trigger authorization and the administrator CLI use the same selected
identity/Profile backend. Preserve cookie name, signing key, Redis key prefix
(also used to name migrated security guards), issuer and URL prefix at cutover.

Sessions use tagged JSON inside SQLCipher. Legacy cache copies support MD5 and
SHA-256 cache addressing, retain expiry, and are decoded with restricted globals;
unsupported values stop import. Logout removes migrated aliases as well as the
current SID. Login throttling, replay guards and endpoint rate limits have atomic
expiry handling in the encrypted DB, not a new Redis persistence dependency.

Multipart uploads use a private SQLCipher spool instead of a plaintext disk spool.
Its per-upload key is private and separate from its DB; normal completion/error
cleanup removes both. Abrupt process/host termination can leave private encrypted
spools and ephemeral key files. Inventory and remove such leftovers only after
confirming no process uses them; do not delete active upload directories.

## Offline Migration and Acceptance

Prepare a consistent, authorized snapshot while all relevant writers are frozen.
Do not pass live data directories to the migration command. Profile snapshots at
schema 11 or 12 are supported; upgrades run on an in-memory copy, not the source.
The input must be a standalone, consistent snapshot without WAL, SHM or rollback
journal sidecars. It is opened read-only and immutable; incomplete snapshots
are rejected rather than checkpointed or repaired.
The Profile input is capped at 256 MiB; larger snapshots need a separately
reviewed migration method. Artifact content is streamed, not loaded in full.

The private JSON plan contains paths, not key values. An example shape is:

```json
{
  "database": "/srv/cx/validation/database/cx.db",
  "key_file": "/srv/cx/validation/keys/cx.key",
  "roots": {
    "results": "/srv/cx/example/received",
    "estimates": "/srv/cx/example/estimated_results",
    "artifacts": "/srv/cx/example/received_padata",
    "inputs": "/srv/cx/example/received_estimation_artifacts"
  },
  "profile_copy": "/srv/cx/validation/snapshot/profile.sqlite3",
  "source_roots": {
    "results": "/srv/cx/validation/snapshot/results",
    "estimates": "/srv/cx/validation/snapshot/estimates",
    "artifacts": "/srv/cx/validation/snapshot/artifacts",
    "inputs": "/srv/cx/validation/snapshot/inputs"
  },
  "session_copy": "/srv/cx/validation/snapshot/sessions"
}
```

The destination pair must not exist. Logical roots need not be opened or populated
to perform the import. Source membership and file identities are rechecked before
publication. Failure leaves an unusable, not-ready destination for diagnosis; do
not point an application at it or retry by overwriting it.

Identity migration uses `utils.cx_migration.export_identity` on an explicitly
provided, frozen legacy user store, then passes its returned in-memory mapping to
`import_snapshot`. It preserves users, invitations, failed-login/replay/rate guard
expiries. The helper neither discovers credentials nor opens a connection. An
optional private `snapshot_export` path supports an already prepared export with
`identity` and `sessions` mappings; it contains secrets and must not be logged,
committed, or left as a permanent plaintext shadow. Prefer in-memory handoff.

Run only against the approved copies, using the candidate Python environment:

```sh
python -B result_server/cx_storage.py migrate-copy --plan /private/copy-plan.json
python -B result_server/cx_storage.py check --plan /private/copy-plan.json
```

Fresh empty instances use explicit `initialize` instead. `rebuild-copy` rebuilds
facts from canonical encrypted bytes, not from old JSON files. Checking covers
SQLCipher page authentication, SQLite/foreign-key integrity, payload/chunk hashes,
canonical record membership, report facts, candidate counts and visibility, and
every published artifact reference. Copy acceptance must additionally compare
search/permissions, all report values/CSV, lineage/version views, bundle members,
Profile/history, invitation expiry and continued signed sessions.

## Backup and Recovery

Copy metadata **first**, then its artifact DB. The metadata snapshot selects a
point in time; immutable generations ensure its references remain available while
the artifact copy is taken. A newer, unreferenced generation in that copy is not
exposed. This is reference-consistent recovery, not a transaction spanning CX,
Budget, Runner and Collector. Each independently owned store needs its own check.

For the candidate CLI, add a new absolute `destination` to the private plan:

```sh
python -B result_server/cx_storage.py backup-copy --plan /private/copy-plan.json
```

`backup-copy` and `recover-copy` create a new metadata file and its `.artifacts`
partner, verify the pair, and never copy the key or overwrite an existing DB.
Back up both, not just metadata or WAL files. Keep key recovery independently
available and test it on a copy. Runtime artifact generations are append-only;
there is no automatic live garbage collection that could invalidate a backup or
in-flight reader. Capacity planning must include retained generations, encrypted
upload spools, WAL, backup copies and restoration workspace.

After new writes, old JSON/Profile snapshots and a storage-unaware release are
**not** a rollback target. Recover a verified current pair with a storage-capable
build, retaining new Results/Estimates, Profile/identity changes, sessions and
uncertain-submission records. If that build/pair is unavailable or incompatible,
stop for recovery; do not inverse-export plaintext or silently lose new writes.
Originals, old snapshots and retired plaintext data are kept until a separately
approved retention/cleanup decision. Database encryption does not encrypt keys,
bootstrap settings, OS logs or application memory.

## Generated-Data Rehearsal

```sh
python -B -m pytest -q result_server/tests/test_cx_persistence.py
python -B result_server/tests/measure_cx_persistence.py --records 1000 --artifact-mib 32
```

The rehearsal creates temporary synthetic snapshots and independent keys, checks
migration plus post-migration writes and pair recovery, and removes its fixtures.
It does not contact services, start containers/CI, collect models or send Results.
Timing and Python-allocation figures are local synthetic measurements, not a
production capacity/RPO guarantee or a measurement of SQLCipher native memory.
