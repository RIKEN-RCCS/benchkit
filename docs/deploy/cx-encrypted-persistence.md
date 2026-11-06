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

## Consistent Document Queries

Result pages, Estimate lists, Version Check lists and Estimate lineage use an
operation-scoped metadata read snapshot in encrypted mode. An enclosing
`CxPersistence.snapshot()` shares its connection with document existence,
permission, payload and affiliation reads. Nested readers reuse that snapshot;
connections and verified document bytes are released when the outer operation exits,
including on errors. Returned documents are independent copies. No permission
decisions or decrypted documents are cached between operations or users.

Lineage source lookup uses the existing UUID index to obtain all candidates,
then checks declared identity, document integrity and current-user visibility.
It does not select just the latest duplicate. Existing parent/conflict/cycle
rules and the different list/detail access rules remain unchanged.

Historical indexes retain unnormalized UUIDs. A declaration-only SQL projection
once per snapshot finds compatibility exceptions; noncanonical declarations,
multi-chunk documents and malformed records use the verified document reader.
This projection still scales with Result bytes/count and is not a constant-time
lookup guarantee. Estimates are read once per snapshot and remain filtered by
the requesting user's permissions. This change requires neither schema changes
nor index rebuilding. Filesystem mode retains its existing behavior and is not
a transactional filesystem snapshot. Indexed navigation is not a replacement
for the full integrity check described below.

## Offline Copy Migration

Use a consistent snapshot with no concurrent writers, not live directories. The
destination databases must not exist. Profile schema 11/12 snapshots are accepted
up to 256 MiB, with no WAL/SHM/rollback-journal sidecars. They are opened read-only
and immutable; schema conversion uses memory and does not repair the input.

Profile columns are matched by name, not physical position. Earlier column-addition
orders are supported when named types, nullability, defaults and primary keys
match; missing, extra or incompatible columns remain errors. Row verification
uses explicit named columns and preserves duplicate rows and ID sequences.
`utils.cx_migration.verify_profile_rows` compares stable, same-version Profile
connections without modifying either database or including row values in errors.

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
| `preserve_legacy_files` | Optional boolean, migration only; default `false` |

With explicit `preserve_legacy_files: true`, files in the Result/Estimate
snapshot directories whose names do not declare a canonical timestamp and UUID
are retained byte-for-byte as encrypted artifacts under the internal
`legacy_files` role. Names retain their original directory role and filename.
No UUID, document, query fact, candidate count or public download binding is
created for these files. Archives are not extracted and unidentified JSON is
not interpreted as an Estimate. Canonically named documents still undergo the
normal strict JSON, identity and permission checks. Source safety, size limits
and snapshot-change checks apply to retained files as well.

Unsupported reference strings remain in the original documents. Preservation
does not make them usable, follow unsafe paths or guess relationships. Keep
backup verification reports that distinguish existing unresolved references
from copy damage. Retained files survive `rebuild-copy`, paired backup and
recovery; verification must include their names and payload hashes, not just
Result/Estimate counts. The logical role uses the existing artifact tables,
but older code may reject it: use a retention-capable build for checking or
recovering such stores. Do not assume an older build is a rollback target.
Remove the migration-only field when preparing a plan for other operations.

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
python -B -m pytest -q result_server/tests/test_document_snapshot.py
python -B result_server/tests/measure_cx_persistence.py --records 1000 --artifact-mib 32
```

The rehearsal generates temporary data and keys, checks migration, subsequent
writes and recovery, and removes its fixtures. It does not contact services or
submit workloads. Synthetic timings are not production performance/RPO guarantees;
Python allocation figures do not include SQLCipher native memory.
