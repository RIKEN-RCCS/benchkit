# Budget Allocation Ownership

## Responsibilities

A Budget owns its scheduler allocation identifier, managed system, enabled state,
validity and management permissions. Execution settings own the GitLab connection
and build/run tags. Runner observations suggest tags; they do not authorize a
scheduler account or select an operating-system identity.

An Execution Profile owns Activity, application/experiment/system scopes and
approval conditions. Its reviewed selection references one Budget destination
per explicit system. Activity is not derived from the Budget label. Budgets do
not implement a balance or consumption limit.

Manual, preview and timer requests share `build_profile_execution_plan`. Broken,
revoked, expired or changed selections never fall back to a legacy target.
Submission still requires the existing target/ref capability declaration and
authorization recheck immediately before network delivery.

## Allocation Storage

Schema 5 stores allocation only in `budget_defaults`, once per Budget. The
`destinations` table contains identity, Budget, system and execution-settings
references; `budget_destinations` projects the allocation for existing catalog
and resolver interfaces. Updating a Budget does not rewrite historical requests
or Result environment snapshots.

Schema 3 and 4 remain readable/writable by the new implementation. Reads and
application startup never upgrade them. The library's compatibility initializer
retains schema 4 unless `normalized=True` is explicit; the lifecycle CLI's `init`
creates schema 5. Legacy `migrate-empty`/`migrate-targets` commands retain their
schema-4 destination. The general database migration CLI explicitly targets 5.

The 4-to-5 migration refuses disagreeing allocation copies. A missing common
settings record can be populated only when its destinations have one allocation
and one execution-settings reference. Conflicting settings require review, not
an inferred first match. Existing IDs, permissions, revision and audit history
are retained. A new numbered migration records the storage change.

## Profile Selection

The Profile editor saves settings and Budget selections in one Profile
transaction. The allocation is not editable there. Selecting Budgets validates
any retained legacy allocation, clears that duplicate, stores the reviewed
snapshot and recalculates the Profile fingerprint. Concurrent Profile changes or
a stale registry revision reject the save.

New Benchkit Profiles created through a Budget-configured Portal require a
selection before they can submit. Approval can save the selection with the
Profile, or leave it pending. Generic Profile edits cannot remove an existing
binding or downgrade this requirement. Existing unbound Profiles retain their
legacy behavior until an explicit mapping is reviewed; editing their descriptive
fields does not automatically assign a Budget.

An allocation-free destination is valid. Empty allocation does not mean disabled
or unauthorized. An unbound Profile with an empty allocation is not automatically
mapped to any Budget. Names and matching identifiers are not assignment rules.

The list, managed view and Usage overview distinguish a Budget-selected Profile
from a legacy direct allocation. They do not display the legacy column as the
current effective allocation for bound Profiles. Authorized edit choices show
current Budget allocations; historical Result snapshots keep their recorded
values. These surfaces do not expose Budget allocations to the public result
view or grant Budget access through Profile ownership.

## Multiple Systems

A grouped Profile selects exactly one destination for every explicit system.
All destinations must use the same GitLab connection and target for one parent
pipeline. Different connections are rejected; the planner never silently splits
the request into extra pipelines or narrows its scope. Existing deduplication,
trigger IDs and schedules are unchanged.

A version-2 execution-route snapshot contains `version`, `registry_revision`,
`target` and `selections`. Each selection contains `budget_id`, `destination_id`
and one-system `route`. The selected system set must exactly match the CI system
selection, without duplicates. File-backed route configuration and version-1
single-destination snapshots keep their interfaces. A single destination still
emits a version-1 CI snapshot. All reviewed destinations are reauthorized and
checked before an explicitly requested subset is planned.

Deploy a CI generator that understands version 2 before enabling grouped
selections for that target/ref. Snapshot contents remain operational metadata,
not public exports or permanent authorization grants. Backend support is explicit:
Benchpark Profiles retain SITE/EXPERIMENT_CONFIG and reject unsupported Budget
or scheduler overrides. Wildcard systems cannot be guessed into destinations.

## Copy Rehearsal

Use the existing database CLI to inspect and rehearse a registry migration:

```sh
python -B -m result_server.db plan --kind budget --database "$REGISTRY" --key-file "$REGISTRY_KEY"
python -B -m result_server.db rehearse --kind budget --database "$REGISTRY" --key-file "$REGISTRY_KEY" --destination "$NEW_COPY"
```

Profile rehearsal takes an explicit mapping array. Each entry contains
`profile_id`, `destination_ids` and the `selection_fingerprint` of the inspected
Profile. There is no default assignment. The local lifecycle tool requires an
explicit trusted local-administrator declaration; it is not an HTTP endpoint and
does not authenticate an arbitrary supplied name as an administrator.

```sh
python -B -m result_server.profile_budget --source "$PROFILE_COPY" --destination "$NEW_PROFILE_COPY" \
  --profile-key-file "$PROFILE_KEY" --registry "$REGISTRY_COPY" --registry-key-file "$REGISTRY_KEY" \
  --registry-revision "$REVISION" --mapping "$REVIEWED_MAPPING" --actor "$OPERATOR" --confirm-local-admin
```

Omit `--profile-key-file` only for an explicitly plaintext legacy source. The
source is opened read-only for copying; only the new copy is migrated. Existing
destinations are never overwritten. Failed copies are retained. The source
Profile schema must already be current; this is not a discovery/repair tool.
The batch applies all Profile mappings in one transaction and rejects a registry
revision change before completion. Trigger definitions and historical requests
are not rewritten. Existing reviewed routes and their original authorizing
identities are preserved; migration cannot silently replace a revoked grant with
the local operator's administrator authority. A changed route requires a separate
selection review. Separate database ownership means this is not a distributed
transaction with the registry; submission-time reauthorization remains required.

## Compatibility and Rollback

Before schema 5, every registry reader/writer must support it, including Web,
timer workers, administrative commands and backup/recovery validators. Updating
one Portal does not authorize migration of a shared registry. The candidate may
operate on schema 4 while these readers are deployed. Backups using a fixed old
code reference must switch to a compatible validator before the registry update.

Old code that accepts only schema 3/4 intentionally refuses 5. Repointing old Web
code at schema 5 is not a rollback. Preserve an encrypted pre-change backup and
compare it on copies. For a new compatibility copy that includes current schema-5
values, the lifecycle tool can materialize schema-4 allocation columns:

```sh
python -B -m result_server.db rollback-copy --kind budget --database "$REGISTRY_COPY" \
  --key-file "$REGISTRY_KEY" --destination "$NEW_COMPATIBILITY_COPY"
```

This never overwrites the source and does not switch any service references.
Using an old backup or compatibility copy operationally requires separately
reviewing all writers, current changes and Profile-format compatibility. Version-2
Profile bindings are not readable by old code; retain the original Profile copy
and do not treat registry rollback alone as whole-system recovery.

Compatibility removal is a separate release decision after all approved
Profiles and registry clients have migrated. It must not become another normal
allocation editing path. Tests cover grouped scope preservation, authorization,
concurrency, source preservation, encrypted backup recovery and rollback copies;
they do not demonstrate scheduler access or a real submission.
