# Portal Execution Profiles Handoff

This note captures the next implementation step after the CX Portal execution
profile registry is merged.

## Current Scope

The current implementation adds the Portal-side foundation:

- A site-local SQLite registry for execution profiles.
- An admin-only `/admin/execution-profiles` page.
- Admin create/update for profile records.
- Profile resolution for `code` / `system` / `exp` targets.
- JSON seed import support for migration or initial setup.

The registry can contain scheduler account or project-group values. Do not
commit real site-local values to the OSS repository.

## Intended Next Step on fncx

Continue the execution path on the fncx CX Portal host, where the real Portal
data directory, service user, GitLab token handling, and received result
artifacts are available.

Recommended order:

1. Configure `RESULT_SERVER_DB_PATH` in the Portal systemd environment.
2. Confirm the admin page can create and update profiles in the live SQLite DB.
3. Add an execution request table for Portal-triggered runs.
4. Add a dry-run submit view that resolves a profile and shows the GitLab
   Pipeline API payload without sending it.
5. Add the real GitLab Pipeline API trigger only after the dry-run path is
   reviewed. Keep the trigger token in the site-local service environment as
   `RESULT_SERVER_GITLAB_TOKEN`; do not store it in SQLite, logs, or the OSS
   repository.
6. Index received benchmark and estimation JSON metadata into SQLite while
   keeping JSON/tgz artifacts as raw records.
7. Add environment snapshot storage after deciding which host/runtime metadata
   should define an environment identity.

GitLab schedules should not be the primary governance point. The Portal should
own periodic and event-triggered execution decisions, then trigger GitLab CI
with resolved site-local variables.

## GitLab Pipeline API Configuration

Dry-run payload rendering requires:

```text
RESULT_SERVER_GITLAB_REPO=gitlab.example.org/group/project
```

Actual submission also requires:

```text
RESULT_SERVER_GITLAB_TOKEN=<site-local GitLab API token>
```

`RESULT_SERVER_GITLAB_REPO` is a scheme-less `host/path` value. The token must
have permission to create pipelines in that GitLab project. The Portal records
the request payload, GitLab response metadata, status, and errors in
`execution_requests`; it must not record the token value.

## Compatibility Expectations

Keep the existing `list.csv` and `queue.csv` paths working. Execution profiles
should act as a site-local override or governance layer, not as a replacement
for app participation registration.

`BK_SCHEDULER_EXTRA_ARGS` and `BK_SCHEDULER_EXTRA_ARGS_<SYSTEM>` remain low-level
escape hatches for bring-up and sites that do not yet use Portal execution
profiles.
