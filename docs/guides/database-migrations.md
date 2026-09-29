# Database Migrations

Migration tooling does not define database ownership or sharing. A shared Budget
registry and a benchmark database isolated by project, environment or operator
are different instances with different lifecycles. Do not combine them, share
keys, or migrate them together just because they use the same command interface.

The current implementation supports **Budget registries only**, using SQLCipher.
Other database types must provide their own migration steps, verification,
backup and concurrency strategy before they can be selected. They need not use
SQLCipher, SQLite, the Budget schema versions, or a shared-server rollout. There
is no database discovery, `all` target, implicit environment lookup, automatic
startup migration, downgrade, or automatic restore.

## One Explicit Instance

Every command requires `--kind`, `--database` and, for the Budget backend,
`--key-file`. The key is read from its existing protected file; never put its
contents on the command line. The DB path selects exactly one instance. Use
separate paths, credentials, permissions and backup locations for isolated DBs.
Directory and file permissions follow the [encrypted Budget guide](budget-registry.md).

```sh
python -m result_server.db status --kind budget --database "$DB_PATH" --key-file "$DB_KEY_FILE"
python -m result_server.db plan --kind budget --database "$DB_PATH" --key-file "$DB_KEY_FILE"
python -m result_server.db verify --kind budget --database "$DB_PATH" --key-file "$DB_KEY_FILE"
```

JSON output reports this code's supported read/write versions, the selected DB's
schema and business revision, and migration history. Status is a compatibility
report, not an integrity check or a report of other running clients. `plan`
performs preflight validation and lists the supported forward steps. `verify`
checks encryption, SQL integrity, references and Budget relationship invariants.
Neither status, plan nor verify writes schema or business records.

`instance_id` is an opaque hash of the database kind, absolute path and filesystem
device/inode. It binds a plan to that local file, not to an environment label or
database contents. Copies, replacements and renamed files require a new plan.
It is not a credential, an authorization control, or a portable business ID.
Output omits database/key paths, credential values and business records.

## Rehearse First

```sh
python -m result_server.db rehearse --kind budget --database "$DB_PATH" --key-file "$DB_KEY_FILE" --destination "$REHEARSAL_PATH"
```

Rehearsal takes a consistent encrypted snapshot into a **new** file, migrates
and verifies that copy, and leaves the original schema/data untouched. It never
switches any Portal to the copy. The copy uses the source DB's key and is just as
sensitive as the source; store it in a protected directory outside the repository.
Do not reuse this key for unrelated databases. A failure leaves the encrypted
copy available for investigation; a repeat must use another destination.
This migrated rehearsal copy is not a pre-migration recovery backup. The actual
migration must still create its own fresh backup of the original schema.

The rehearsal snapshot can become stale while users edit the original. Inspect
and plan the original again immediately before the approved migration window.

## Apply One Plan

1. Identify all clients of **this instance**, including background writers. For
   a shared DB, deploy code compatible with both old and new schemas to those
   clients first. An isolated DB does not require unrelated clients to update.
2. Validate the encrypted rehearsal and recovery procedure. Keep the recovery key
   separate from backups. Coordinate a brief write-maintenance window for this
   DB; do not stop unrelated services or assume an idle UI means no writers.
3. Run `plan` again and copy its `schema_version`, `revision` and `instance_id`
   into the explicit migration arguments below. Confirm the path and client
   compatibility before applying. The CLI cannot discover all remote clients.
4. Verify application behavior and reopen writes after successful verification.

```sh
python -m result_server.db migrate --kind budget --database "$DB_PATH" --key-file "$DB_KEY_FILE" \
  --expect-version "$SCHEMA_VERSION" --expect-revision "$REVISION" --expect-instance "$INSTANCE_ID" \
  --backup "$BACKUP_PATH" --confirm
python -m result_server.db verify --kind budget --database "$DB_PATH" --key-file "$DB_KEY_FILE"
```

The SQLCipher runner acquires `BEGIN IMMEDIATE` **before** backup. While holding
that writer lock, it rechecks the plan, creates and validates an encrypted backup
using a separate read-only connection, applies the numbered steps, records their
IDs/versions/UTC timestamps, and verifies the result before committing. The
backup therefore contains the immediately preceding committed state, including
WAL contents, without a backup-to-migration writer gap. All steps and migration
history commit together. The business-edit revision and history are not reused
as migration history. Old clients are not made compatible by the writer lock;
they must already support the resulting schema before writes resume.

A stale version, revision or instance ID fails before backup or migration.
Concurrent writers wait or receive their normal busy/timeout error. A second
migrator using the previous plan fails after the first commits. Replanning an
already-current DB yields an empty plan and applying that plan makes no backup
or history entry. Existing backups, DBs and keys are never overwritten.

If any step or verification fails before commit, the entire schema/data/history
transaction rolls back. The encrypted backup remains available. There is no
automatic restore: after writes resume, restoring an older backup could discard
new data. Stop writers and review recovery explicitly. Restoring or replacing a
live main file without its WAL handling is not a supported recovery procedure.

## Per-Database Evolution

Prefer compatible expansion, a code transition, and later removal of obsolete
structures. A semantic change such as one-to-many destinations still needs an
explicit compatibility review; adding a version number alone is not sufficient.
Each backend owns its version namespace and its supported upgrade paths. New
steps must be tested with populated old-format fixtures, failure rollback,
concurrency and encrypted backup/recovery where encryption applies. Do not use
current application defaults or real site identifiers as migration invariants.

The Budget adapter supports the reviewed populated v3-to-v4 upgrade and empty
v1/v2 prototypes only. Populated prototypes and unknown schemas are rejected.
The earlier `budget_db migrate-empty` and `migrate-targets` CLI commands retain
their names but now use the same locked-backup runner. Prefer `db plan` and the
explicit expected-state arguments for future operations.
