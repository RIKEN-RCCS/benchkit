# Encrypted Budget Registry

The budget registry is an independent SQLCipher database for shared execution
configuration. An opt-in Portal management view is available; profile selection
and pipeline submission are not yet connected. No existing databases are
converted and no shared database is opened automatically at application startup.

## Security Boundary

Encryption protects database contents when a database file or encrypted backup
is disclosed **without its key**. It does not protect against a compromised
application that can read the key, an authorized query, or disclosure through
logs, CI variables, artifacts, memory, or unencrypted exports. Access control,
process isolation, and backup policy remain necessary.

The registry requires SQLCipher 4.5.1 or newer within version 4, with encrypted headers and memory-backed
temporary storage. Missing keys, an unsupported driver, plaintext databases,
unsafe permissions, and invalid keys cause errors. There is no SQLite fallback.
WAL page contents are encrypted; sidecar metadata can still expose filesystem
information. See the [SQLCipher security design](https://www.zetetic.net/sqlcipher/design/)
and [key and integrity APIs](https://www.zetetic.net/sqlcipher/sqlcipher-api/).

Keys are random 32-byte binary files, not passwords. Keep them outside the
database directory, repository, logs, command arguments, and database backups.
The CLI accepts a key **path**, never a key value. Supply the file through a
separately controlled credential mechanism. Loss of all copies of the key means
loss of access to the database. The application does not guarantee erasure of
Python objects, process memory, swap, or core dumps.

## Install and Initialize

On Linux x86-64, the optional dependency is:

```sh
python -m pip install -r requirements-budget-db.txt
```

This uses the [sqlcipher3 maintainer's binary distribution](https://github.com/coleifer/sqlcipher3),
not a Python standard-library feature. Other platforms need a vetted
`sqlcipher3` build with SQLCipher 4 and `SQLITE_TEMP_STORE=2` or `3`. Review the
bundled SQLite, crypto provider, platform support, and license notices before
deployment. Update and test the dependency as security releases become available.

Set `DB_PATH`, `DB_KEY_FILE`, and `BACKUP_PATH` to operator-selected absolute
paths. Provision their parent directories with mode `0700` first. The key and
database must be in separate directories; file modes must be `0600` or stricter.
Symlinked paths and multiply linked files are rejected. This initial deployment
model assumes services run as the same OS user on local storage, not over NFS.

```sh
python -m result_server.budget_db generate-key --key-file "$DB_KEY_FILE"
python -m result_server.budget_db init --database "$DB_PATH" --key-file "$DB_KEY_FILE"
python -m result_server.budget_db check --database "$DB_PATH" --key-file "$DB_KEY_FILE"
python -m result_server.budget_db backup --database "$DB_PATH" --key-file "$DB_KEY_FILE" --destination "$BACKUP_PATH"
```

Creation refuses to overwrite any existing key or database. Schema creation is
explicit; reads do not create missing databases or migrate schemas. A failed
initialization may leave an incomplete file for operator inspection; it is never
silently replaced. All readers must support the schema version before a shared
schema is upgraded.

Schema version 3 adds references to server-configured GitLab targets. It retains
system-specific budgets, manager assignments and a single budget enabled state.
An unused version-1 or version-2 prototype can be upgraded explicitly, with a required new
encrypted backup destination:

```sh
python -m result_server.budget_db migrate-empty --database "$DB_PATH" --key-file "$DB_KEY_FILE" --destination "$BACKUP_PATH"
```

The command refuses a registry with any records or prior revisions. Populated
registries need a separately reviewed migration; no users, systems, or states
are silently discarded. Neither reads nor application startup perform migration.

## Backup and Recovery

The backup operation uses a consistent SQLite backup transaction, including
committed data still in WAL, and writes an encrypted destination using the same
key. It checks page authentication, logical integrity, and references. Do not
copy only a live database's main file or use plaintext SQL dumps as backups.

Keep recovery key copies in a separate access-controlled backup system, not in
the database backup set. Restore to a new private directory and run `check` with
the separately recovered key before switching any service to that database.
Rehearse this procedure. Encryption does not establish backup freshness or
prevent replacement with an older valid database.

Key rotation is not implemented by this CLI. It requires coordinated clients,
an encrypted export or supported rekey procedure, verified recovery, and an
explicit treatment of backups encrypted with the old key. Do not regenerate
the key file for an existing database.

## Registry Contracts

- Budgets, manager assignments, GitLab connections, execution settings, and budget-system
  destinations are separate records. Destinations reference reusable settings
  and connections. The database stores credential references, not token values.
- Each budget belongs to exactly one immutable system and has at most one
  execution destination. Its single enabled state controls resolution.
  A destination ID cannot be moved to another budget or system. Different
  budgets can use the same system and GitLab project without ambiguity.
- CX administrators manage the entire registry, including manager assignments
  and infrastructure. Budget managers can edit their own budget settings and
  resolve its destination. They cannot grant management rights, reassign
  infrastructure, or modify another budget. Activity management does not imply
  budget management access.
- Every change checks a global revision inside a write transaction and records
  the actor and before/after values in encrypted history. Stale saves fail.
- Resolution checks CX administrator or assigned manager authority, enabled state and validity within one read
  transaction. Its value snapshot includes the revision and resolved route.
  This is not yet wired into pipeline submission or persisted execution records.
- Authentication must construct `RegistryActor` on the server. Never obtain
  `is_admin` or the actor identity from submitted form fields.

## Portal Management

Configure `RESULT_SERVER_BUDGET_DB_PATH` and `RESULT_SERVER_BUDGET_DB_KEY_FILE`
with the existing database and key paths. Multiple Portal instances can refer
to the same files. Startup only registers configuration and routes: it does not
create or migrate storage. Missing configuration, an inaccessible key, or an
invalid database makes the management view unavailable without creating files.

The authenticated `/budgets/` view starts with a **Budget @ System** list.
A budget is a system-specific resource entitlement with managers, validity dates,
and one enabled state. Its scheduler allocation ID is the system-specific accounting
argument, not a running job's allocation ID and not a public Activity label.
A different system requires a separate budget, even if its label or manager is
the same. Application applicants and end users are not registered in this
registry. Their request and approval workflow is separate from the budget
manager's authority to configure CX execution using the budget.

Selecting a list entry brings its budget, runner tags, GitLab connection selector,
and managers onto the same page. Selecting saved execution settings fills the
tags and connection. The budget form does not accept GitLab URLs, repository paths,
credential references or ID-token audiences. Validity dates are optional.

Connections configured through `RESULT_SERVER_GITLAB_TARGETS` (or the existing
single-repository fallback) appear automatically. Saving a selection records only
the target reference, not a second copy of its URL, project or credential reference.
The current server configuration supplies those values when resolving the
destination. All Portals sharing a registry must agree on target IDs and their
destinations. Changing server configuration does not increment the registry
revision; review tickets also bind the selected connection details, and applying
a review after those details change fails. Removing a target makes its saved
reference unavailable rather than falling back to a different connection.

CX administrators can inspect connections under **Infrastructure / Connections**.
Server-configured targets are read-only there. Additional registry-managed
connections can be registered and edited there once, then reused by budgets.
Credential references contain environment-variable names, never token values.
This registration does not provision credentials or test remote access.

OS account names are not configuration inputs and are not returned in execution
snapshots: the runner's deployment determines its OS identity. The storage schema
retains a retired account-name column to preserve existing records without an
implicit migration; new records leave it empty. Validity dates remain optional.

Budget, destination and runner-tag edits are reviewed and saved in one transaction.
A newly used server target reference is recorded in that same transaction.
Validation failure or preview leaves no partial records or history changes behind.
Reusing unchanged settings preserves their IDs and creates no extra history for
those shared settings. The budget form cannot alter a connection's configuration.
Changing shared tags, or editing a registry-managed connection through Infrastructure,
lists every affected budget during review. Credential provisioning, OS accounts,
and runner registration are not performed by these forms.

The default ID-token audience resolves to the selected GitLab server URL.
Exceptional runner requirements belong under **Infrastructure / Execution settings**.
Budget edits preserve an existing custom audience. Switching that execution record
to another connection while a custom audience is set requires the Infrastructure
editor, where both settings can be reviewed together.

Internal IDs are generated automatically for new records and preserved on
edits. An existing budget's system is read-only; changing systems requires
creating a separate budget, not changing the meaning of an existing ID.
The administrator-only Infrastructure menu holds shared connection and advanced
runner configuration. No separate registration is required for existing server
targets. Internal IDs and recent history are collapsed on the budget screen.

CX administrators can manage all sections and assign registered Portal accounts
as budget managers. Account existence is checked at both review and apply.
Budget managers can edit only their own budget settings, not manager, account,
connection, or destination assignments. No end-user/operator role exists here.
Unassigned users cannot access management. The public Portal
surface denies these routes. All responses are marked `no-store`.

Administrator status is reloaded from the user store on every request, and
budget manager authority is checked in the encrypted registry. Session affiliation
labels alone do not grant management access. An unavailable identity backend
does not fall back to cached privileges. Deployment must use a trusted user
directory and must not grant administrative rights to untrusted accounts.

Changes go through review and explicit shared-registry confirmation. Review
uses the same validation and authorization as writes, inside a transaction
that is rolled back; no revision or history entry is committed. The preview
shows before/after fields and affected destinations. Confirmation uses a
signed proposal bound to the actor and revision, expiring after ten minutes.
Changed proposals, stale revisions, replayed submissions, expired reviews,
revoked access, and missing CSRF tokens are rejected. No proposal is stored in
an unencrypted draft database or a URL. The signed browser proposal is not
encrypted and contains operational fields, so browser access remains sensitive.

The storage API itself still applies successful writes immediately. Persistent
drafts, separate approvers, and cross-database profile impact analysis are not
implemented. The current review identifies affected registry destinations,
not every external profile or scheduled trigger. Updates to enabled records
affect subsequent resolution after confirmation.

Profile references, execution selection, and the shared manual/scheduled/watch
resolver remain pending. Runner registration, scheduler authorization, and CI
input compatibility still require validation before execution is enabled.
