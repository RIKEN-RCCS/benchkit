# Encrypted Storage for Results, Profiles, Sign-In State and Artifacts

This optional SQLCipher backend stores data retained by the portal between
restarts. Existing storage remains the default; enabling the backend is an
explicit migration, not an automatic upgrade.

## Scope and Compatibility

Each instance uses two encrypted databases:

- Metadata: complete Result/Estimate documents, search facts and visibility,
  execution profiles, approvals and submission history, users/affiliations,
  TOTP secrets, invitations, sessions and expiring authentication guards.
- Artifacts: immutable generations of measurement archives, estimation bundles
  and retained input files.

Documents, search facts and receipt metadata commit together. Artifact bytes are
committed before their references become visible, so a failed upload does not
replace the previous complete data or hold the metadata writer lock throughout
the upload.

JSON APIs and exports remain supported. Migration preserves saved bytes, unknown
fields, filenames, UUIDs, scientific values and existing access rules. It does
not reconstruct unsaved HTTP data or repair unresolved references by guessing.
Budget, Runner observations and Collector state remain independently owned;
this backend does not migrate them.

## Configuration

Use the instance application factory and install both existing requirement sets:
`requirements-result-server.txt` and hash-pinned `requirements-budget-db.txt`.
The stub-authentication development factory does not support this backend.

Configure absolute paths for both bindings:

```text
RESULT_SERVER_PERSISTENCE_DB=/example/private/cx.db
RESULT_SERVER_PERSISTENCE_KEY=/example/keys/cx.key
```

These are placeholders, not deployment locations. The artifact database defaults
to `cx.db.artifacts`; `RESULT_SERVER_PERSISTENCE_ARTIFACT_DB` may select another
private path. Both databases use the instance key. Generate it with the existing
key helper and keep its value out of configuration, logs and backup payloads.
Keep the key outside both database directories. Directories require mode 700,
files mode 600; symlinks and hard links are rejected.

Logical roots retain existing URL identities and must remain distinct. Keep both
databases and the key outside those roots. They correspond to `RECEIVED_DIR`,
`ESTIMATED_DIR`,
`RECEIVED_MEASUREMENT_ARTIFACTS_DIR` and `RECEIVED_ESTIMATION_ARTIFACTS_DIR`.
`RESULT_SERVER_LEGACY_INPUTS_DIR` optionally binds separately inventoried historical
inputs. Encrypted mode does not write document or extracted artifact files there.

Startup checks configuration, readiness, schemas and database-pair identity. It
does not initialize, migrate or rebuild storage. Missing keys/drivers, incomplete
migration or an incompatible pair fail closed, without plaintext/Redis fallback.
Existing sessions require compatible cookie, signing-key and namespace settings.

## Offline Copy Migration

Use a consistent snapshot with no concurrent writers, not live directories. The
destination databases must not exist. Profile schema 11/12 snapshots are accepted
up to 256 MiB, with no WAL/SHM/rollback-journal sidecars. They are opened read-only
and immutable; schema conversion uses memory and does not repair the input.

The CLI accepts a private JSON plan. A migration plan has these fields:

| Field | Value |
| --- | --- |
| `database`, `key_file` | Absolute destination metadata DB and existing key paths |
| `artifact_database` | Optional absolute destination artifact DB path |
| `roots` | Logical absolute paths keyed by `results`, `estimates`, `artifacts`, `inputs`; optional `legacy_inputs` |
| `profile_copy` | Standalone Profile snapshot path |
| `source_roots` | Snapshot directories with the same roles as `roots` |
| `session_copy` | Optional private legacy session snapshot directory |
| `snapshot_export` | Optional private JSON export containing `identity` and/or `sessions` |

Identity exports can be prepared with `utils.cx_migration.export_identity` using
an explicitly supplied frozen legacy user store. The export contains secrets;
prefer in-memory handoff to `import_snapshot`. Do not log, commit or retain a
plaintext export as a second authoritative store. Unsupported session values stop
import. Preserve invitation/session/security-guard expiries.

```sh
python -B result_server/cx_storage.py migrate-copy --plan /example/private/plan.json
python -B result_server/cx_storage.py check --plan /example/private/plan.json
```

From the repository root, `python -B -m result_server.cx_storage` supports the
same arguments. Neither invocation requires a `PYTHONPATH` override.

Use `initialize` only for new empty instances. `rebuild-copy` rebuilds derived
facts from encrypted documents, not old JSON. Interrupted imports are not ready
for use and must not be overwritten or selected as application storage.

Checks cover encrypted-page/SQL/foreign-key integrity, payload hashes, document
and query membership, visibility and published artifact references. Acceptance
also requires application-level comparisons of permissions, search, reports/CSV,
history, sessions and artifact downloads; database integrity alone is insufficient.

## Backup and Recovery Requirements

Back up metadata **before** the artifact database. Immutable generations keep
that metadata snapshot's references available during the second copy. Back up
both databases, not just metadata or WAL files. This is not a globally atomic
snapshot across independently owned stores.

Add an absolute `destination` to a private plan and use `backup-copy` or
`recover-copy`. Both create a new metadata file and its `.artifacts` partner,
verify the recovered pair, and neither overwrite a database nor copy the key.
Keep key recovery independently available and test recovery on a copy.

After new writes, a storage-unaware release or old JSON/Profile snapshot is not
a safe rollback target. Recovery needs a compatible build and a verified current
database pair that retains those writes. Do not silently discard new data or
inverse-export plaintext as a fallback.

There is no automatic live artifact-generation garbage collection. Include old
generations, WAL, encrypted upload spools, backups and recovery workspace in
capacity planning. Multipart spools are encrypted; normal completion/error removes
their temporary keys and data. Abrupt termination can leave private remnants;
only remove them after confirming they are unused. Database encryption does not
protect application memory, OS logs, bootstrap settings or separately held keys.

## Tests

```sh
python -B -m pytest -q result_server/tests/test_cx_persistence.py
python -B result_server/tests/measure_cx_persistence.py --records 1000 --artifact-mib 32
```

The rehearsal generates temporary data and keys, checks migration, subsequent
writes and recovery, and removes its fixtures. It does not contact services or
submit workloads. Synthetic timings are not production performance/RPO guarantees;
Python allocation figures do not include SQLCipher native memory.
