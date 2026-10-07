# Encrypted Budget Registry

The budget registry is an independent SQLCipher database for shared execution
configuration. An opt-in Portal management view and explicit profile bindings
are available. Budget-backed submission requires a separately enabled CI target/ref.
No existing databases are
converted and no shared database is opened automatically at application startup.

The separate [runner observations view](runner-monitoring.md) provides read-only
GitLab runner inventory and status; it does not change Budget configuration.

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

On Linux x86-64 with CPython 3.12 or 3.13, install the optional dependency
separately from other requirements:

```sh
python -m pip install -r requirements-budget-db.txt
```

The requirements file permits only the reviewed wheels and enforces SHA-256
verification. Do not combine it with unhashed requirements in one pip invocation:
pip's hash-checking mode applies to every requirement in that invocation.
Unsupported artifacts fail rather than falling back to a source build.
An already-installed distribution is not revalidated by this command; use a fresh
environment for artifact verification and compare installed files separately.

This uses the [sqlcipher3 maintainer's binary distribution](https://github.com/coleifer/sqlcipher3),
not a Python standard-library feature. Other platforms need a vetted
`sqlcipher3` build with SQLCipher >=4.5.1,<5 and `SQLITE_TEMP_STORE=2` or `3`.
Operators select a supported build for their platform and apply and test
applicable security updates, including updates to its bundled components.

### Dependency Maintenance

SQLCipher follows the same [dependency and deployment responsibilities](../../SECURITY.md#dependency-and-deployment-responsibilities)
as other external software. This guide defines installation and compatibility
requirements, not a public inventory of any deployed server. Operators manage
their installed versions, security updates, and operational records privately.
Do not include keys or credentials in those records.

For a dependency update, review each supported wheel from the
[release metadata](https://pypi.org/pypi/sqlcipher3-binary/0.6.0/json), compare its
downloaded SHA-256 with the published digest, check upstream release and security
notes, and replace the version and hashes together. Run the encrypted database
tests on both supported Python versions in fresh environments. A matching hash
identifies an artifact; it does not guarantee absence of vulnerabilities.
These requirements do not vendor the wheels or their source code into this repository.

The encrypted database CI job records the installed wheel filename and SHA-256
from pip's installation report, along with the Python, SQLCipher, SQLite, and
crypto provider versions, for each supported Python version. The runtime probe
uses an in-memory database and an ephemeral key; it does not open configured
databases or read deployment keys. Only selected package metadata is logged, not
the raw pip report or deployment paths. This evidence describes the CI environment,
not a running deployment or a certification of upstream binaries. It does not
require operators to publish equivalent records for their servers.

### Initialization

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

Schema version 4 separates the managed system from canonical execution targets.
It retains manager assignments and a single budget enabled state. Schema version
3 added references to server-configured GitLab targets.
An unused version-1 or version-2 prototype can be upgraded explicitly, with a required new
encrypted backup destination:

```sh
python -m result_server.budget_db migrate-empty --database "$DB_PATH" --key-file "$DB_KEY_FILE" --destination "$BACKUP_PATH"
```

The command refuses a registry with any records or prior revisions. Populated
version-1/2 registries need a separately reviewed migration; no users, systems,
or states are silently discarded. Neither reads nor application startup perform migration.

For a populated version-3 registry, deploy version-4-capable code to **every
reader and writer first**, stop shared-registry writes, then run:

```sh
python -m result_server.budget_db migrate-targets --database "$DB_PATH" --key-file "$DB_KEY_FILE" --destination "$BACKUP_PATH"
```

This takes a new encrypted backup, validates the existing relationships, and
replaces the single-destination constraint with uniqueness per budget and
execution target in one transaction. IDs, manager assignments, enabled states,
validity dates, revision and history are preserved. Existing budgets initially
retain their former system as the managed system and their one execution target.
No name-prefix or runner-tag inference merges budgets or broadens access.
New code continues to read and edit version-3 singleton budgets without migration;
the grouped editor requires version 4. Older code rejects version 4, so migrating
a shared database is not an isolated UI deployment. Run `check` after migration
and keep the backup and its separately stored key for recovery. Do not restore
over a live database or discard subsequent edits during rollback.

## Backup and Recovery

The [single-instance migration workflow](database-migrations.md) provides
`status`, `plan`, encrypted-copy `rehearse`, guarded `migrate`, and `verify`.
It applies only to the explicitly selected DB, not every DB or Portal deployment.
Use it for planned upgrades; the older migration commands also use its locked
backup and transaction handling.

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

## Profile Comparison Preview

An operator with filesystem access to both databases and the registry key can
compare one existing profile database with registered destinations:

```sh
python -m result_server.budget_profile_preview --database "$DB_PATH" \
  --key-file "$DB_KEY_FILE" --profile-database "$PROFILE_DB_PATH"
```

Use the GitLab target configuration of that profile database's Portal instance.
Run separately for each instance; profile IDs are not globally unique. Both
databases are opened read-only, without creation or migration. Their snapshots
are individually consistent, not an atomic cross-database snapshot.

The JSON lists each profile/system/saved-trigger combination and same-system
Budget candidates, with reasons requiring review. An absent saved trigger leaves
the previous target unknown; an empty target in a saved trigger uses the configured
default, as submission does. Empty profile allocation is unspecified, never an
implicit match to a scheduler default. Unbounded system scopes are not expanded.
Target comparison uses the effective server/project binding, not display labels.

Output is for administrators, not public artifacts: it includes record IDs and
system names, but omits allocation values, credentials, endpoint URLs and profile
metadata. No candidate is automatically selected or declared ready to execute.
This preview does not compare runner tags, check token availability, or authorize
a submission. Future application must recheck permissions, validity, connections,
runner constraints and registry revision. No profiles, jobs or settings are changed.

## Selected-Destination Planning

`utils.budget_pipeline.build_budget_pipeline_plan` provides a planning API for a
trusted stored profile, authenticated registry actor, explicitly selected
destination and expected registry revision. It resolves the destination using
current Budget permissions and validity, derives the GitLab project and runner
settings, and refuses conflicting profile allocation or scheduler overrides.
One plan selects one canonical execution system, even when its profile or
managed system covers several targets. It does not infer a Budget from an empty
allocation or the first configured GitLab target.

The plan carries a value snapshot in `BK_EXECUTION_ROUTE_SNAPSHOT`; the CI
generator verifies its schema, selected system and server/project binding before
generating jobs. Credential references remain outside that variable. The
snapshot includes operational IDs, tags and allocation: keep it out of public
output and restrict pipeline-variable and artifact access. It is not signed and
does not authorize a CI editor to use an otherwise inaccessible resource.

The planning API itself does not save a selection, read a token or submit a
pipeline. Manual, scheduled and watch submission paths use a separately stored
binding and recheck its authority and configuration. A previously generated
plan is not a durable permission grant.

### Profile Bindings

CX administrators can edit a registered, approved, single-system profile and
save its Budget selection. Budget managers continue managing their assigned
Budget settings; this does not grant access to the CX administrator profile
editor. No applicant membership is introduced. Multi-system profiles remain
unchanged and cannot be silently narrowed by selecting a single destination.

The binding is stored in the existing profile database metadata, not the Budget
database, with its authorizing identity, profile fingerprint and reviewed route
snapshot. No schema migration or automatic assignment is performed. Generic
profile updates and request approvals cannot create, remove or replace a binding.
Relevant profile changes require reviewing the selection again. Saving checks
the rendered profile state and registry revision to detect concurrent edits.

Submissions recheck the saved authorizing identity against the current user
directory, Budget permissions and validity, and the reviewed execution settings.
Unrelated registry revisions do not invalidate an unchanged destination. Missing
or malformed bindings, revoked authority and changed settings block submission;
they do not fall back to the legacy GitLab selector. Bindings are not implicitly
cleared by an empty form value. Legacy profiles without a binding retain their
existing behavior. Trigger request records include the resolved snapshot; treat
these records and the profile database as operational data, not public exports.
Budget database encryption does not encrypt this separate profile database.

### Enable Submission

Before enabling a Budget-backed target/ref, deploy CI code that consumes and
validates `BK_EXECUTION_ROUTE_SNAPSHOT`, verify runner/ref access and variable
restrictions, and configure `RESULT_SERVER_BUDGET_PIPELINE_TARGET_REFS` on each
submitting process. Its value is a JSON object mapping configured GitLab target
IDs to exact refs, for example `{"example":["develop"]}`. There is no wildcard
or default-target grant. A missing, invalid or nonmatching grant blocks network
submission, including scheduled and watch triggers, while selection and dry-run
planning remain available. Ordinary legacy submissions are unaffected.

The standalone trigger runner also needs the Budget database/key path settings,
SQLCipher runtime, and its own explicit `RESULT_SERVER_REDIS_PREFIX` alongside
`REDIS_URL` for the matching user directory. Never borrow another instance's
identity namespace. Identity failures are fail-closed, and credentials are not
stored in bindings or snapshots. Allowlisting a ref is an operator assertion of
CI capability, not a signed attestation or protection against CI editors.

## Registry Contracts

- Budgets, manager assignments, GitLab connections, execution settings, and budget-system
  destinations are separate records. Destinations reference reusable settings
  and connections. The database stores credential references, not token values.
- Each budget belongs to exactly one immutable **managed system** and may expose
  multiple explicitly selected **execution targets**. Its single enabled state,
  validity dates and manager assignments control every target. Common execution
  settings and allocation are saved independently of the first target.
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

The authenticated `/budgets/` view starts with a **Budget @ Managed system** list.
A budget is a managed-system-specific resource entitlement with managers, validity dates,
and one enabled state. Its scheduler allocation ID is the system-specific accounting
argument, not a running job's allocation ID and not a public Activity label.
A managed system may contain several machine types or partitions. For example,
`Example Computing Center` can own one budget with `Example_A` and `Example_B`
as execution targets. They may use the same login runner with different scheduler
partitions, or different runners/connections. Application applicants and end users are not registered in this
registry. Their request and approval workflow is separate from the budget
manager's authority to configure CX execution using the budget.

Selecting a list entry opens the budget's managed system, common runner tags,
GitLab connection and execution targets, with a link to manager assignments.
Selecting saved execution settings fills the
tags and connection. The budget form does not accept GitLab URLs, repository paths,
credential references or ID-token audiences. Validity dates are optional.

The grouped editor at `/budgets/group` selects exact execution-target IDs from
`config/system.csv`. These IDs still drive `system_info.csv`, application matrix
rows, scheduler queues/partitions and results. The managed-system label never
replaces them in the resolved route. Targets are revalidated during both review
and apply. Optional run-tag filtering is only a discovery aid and never unchecks
selected targets or grants access automatically.

Each target uses the common GitLab/tag settings unless a saved execution-setting
record for the same managed system is explicitly selected. Alternative settings
can be registered under Infrastructure without duplicating the budget or its
managers. Review binds both common and alternative connection configurations.
One optional scheduler allocation applies to all targets in a budget; distinct
allocations require distinct budgets. Review lists added, retained and removed
targets, including current and proposed settings/allocation. Removing a target
records its removal and makes its destination ID unresolvable; it does not cancel
jobs or change previously captured snapshots. Existing target IDs are preserved.

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

Budget, destination and runner-tag edits are validated and saved atomically.
A newly used server target reference is recorded in that same transaction.
Validation failure or preview leaves no partial records or history changes behind.
Reusing unchanged settings preserves their IDs and creates no extra history for
those shared settings. The budget form cannot alter a connection's configuration.
Changing shared tags, or editing a registry-managed connection through Infrastructure,
lists every affected budget during review. Credential provisioning, OS accounts,
and runner registration are not performed by these forms.

The Budget overview shows each authorized budget's scheduler allocation ID.
Saved execution-setting choices show their GitLab connection, build/run tags,
and system rather than a budget-derived name. Identical combinations include
their record IDs to distinguish separately shared settings. Renaming a budget
does not rename or modify these settings; existing record names and references
are preserved. New settings created through the Budget form use a neutral name.

Scheduler allocation IDs are optional. Leave the field empty for a system that
does not require an allocation override. Empty is stored and resolved as an empty
string, not a fabricated account ID or a public Activity label. Scheduler access
and site defaults still apply.

**Add budget** is the registration entry point for both one and multiple execution
targets. Selecting multiple targets creates one Budget, not separate Budgets for
each target. Independent Budgets are registered individually through the same form.
The overview no longer includes a separate single-target creation form.
Budget names link to their editor; there is no duplicate Edit action column.
Execution-target rows display the GitLab connection and build/run tags that will
be saved, including unsaved edits to the common settings. A target-specific
selector appears only when alternative saved settings exist for the same managed
system. Other scopes and the common record itself are not offered as alternatives.
An unavailable selected override must be corrected explicitly, never silently
replaced by the common settings.

Changing the managed-system name while registering a budget retains entered tags.
If the selected saved settings belong to another scope, choose matching settings
or explicitly choose new settings before saving. Scope checks still apply on the
server. Runner match summaries show counts rather than repeating names; their
links open the connection-filtered inventory separately from the editor.

The existing Status column distinguishes disabled, not started, expired,
unconfigured, and within-validity budgets. Dates are inclusive in UTC. These
labels describe registry state, not runner availability or submission readiness.
Recent changes show record names and operations; changed field names are available
on expansion without displaying before/after operational values in the list.

The former separate-budget batch page redirects to Add budget. Previously opened
batch forms and signed batch reviews cannot be submitted; use
Add budget. Existing records are preserved, never automatically merged or deleted.
Registries on schema v3 retain their single-target editor until explicitly migrated.
The shared registry affects every connected Portal even when the editor is opened
in only one deployment. No pipelines are started by registration.

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

Ordinary registration and edits use **Save budget** and return to the Budget list
with a one-time success notice and the saved row highlighted. Manager assignments
return to the manager panel; Infrastructure changes return to their section.
The shared-registry scope is a standing label, not a checkbox on every save.

Validation errors retain the grouped editor's entries and selected targets.
Invalid date intervals are marked at the date field. A revision conflict retains
the proposal but requires a new review against current records before saving;
there is no automatic retry or overwrite. Recovery from an apply failure uses
only the actor-bound, unexpired signed proposal, not replacement POST fields.
Recovery does not save drafts in browser storage, cookies, or an auxiliary DB.

Changing execution settings referenced by another Budget opens a review showing
those Budgets. Infrastructure changes affecting Budgets also require confirmation.
References include saved common settings even when current targets use overrides.
Reusing unchanged settings or editing only the current Budget does not require
this review. Impact is determined server-side and rechecked when applying.

Every save retains validation, authorization, CSRF and revision checks. Validation
uses the same storage rules in a rolled-back preview before the write; a stale
revision or changed connection aborts the write without partial changes. Where
review is required, it shows before/after fields and affected Budgets, and uses a
signed proposal bound to the actor and revision, expiring after ten minutes.
Changed proposals, stale revisions, replayed submissions, expired reviews,
revoked access, and missing CSRF tokens are rejected. No proposal is stored in
an unencrypted draft database or a URL. The signed browser proposal is not
encrypted and contains operational fields, so browser access remains sensitive.

The storage API itself still applies successful writes immediately. Persistent
drafts, separate approvers, and cross-database profile impact analysis are not
implemented. The current review identifies affected registry destinations,
not every external profile or scheduled trigger. Updates to enabled records
affect subsequent resolution after saving.

Profile references, execution selection, and the shared manual/scheduled/watch
resolver remain pending. Runner registration, scheduler authorization, and CI
input compatibility still require validation before execution is enabled.
