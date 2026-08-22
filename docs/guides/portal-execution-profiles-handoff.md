# Portal Execution Profiles Handoff

This note captures the current CX Portal execution-profile rollout status and
the remaining follow-up work after the registry, submit path, and trigger runner
were merged.

## Current Scope

The current implementation includes the Portal-side foundation and execution
path:

- A site-local SQLite registry for execution profiles.
- An admin-only `/admin/execution-profiles` page.
- Admin create/update for profile records.
- Profile resolution for `code` / `system` / `exp` targets.
- JSON seed import support for migration or initial setup.
- Portal-triggered execution request records.
- Admin dry-run and confirmed GitLab trigger submit paths.
- Portal-managed scheduled and repo/ref trigger definitions.
- A site-local trigger runner for scheduled and event-triggered execution.
- Trigger decision visibility in the admin profile page and result-level run
  cause visibility for results produced by Portal-triggered pipelines.

The registry can contain scheduler account or project-group values. Do not
commit real site-local values to the OSS repository.

## Deployment Status

The CX Portal rollout has completed the execution-profile submit path and the
initial trigger-runner path. Each live Portal host owns its real Portal data
directory, service user, GitLab token handling, and received result artifacts.
Keep site names, hostnames, tokens, service paths, and local database paths in
the site-private operations notes, not in this public repository.

Completed:

- `RESULT_SERVER_DB_PATH` can point the Portal at the live site-local SQLite DB.
- The admin page can create, update, pause, resume, and delete profiles and
  trigger definitions in the live DB.
- Portal-triggered requests are recorded in `execution_requests`.
- The admin dry-run submit view resolves a profile and renders the GitLab
  pipeline trigger payload without sending it.
- Real GitLab trigger submission is available after admin confirmation. Keep
  trigger tokens in the site-local service environment; do not store them in
  SQLite, logs, or the OSS repository.
- The site-local trigger runner evaluates scheduled and `repo_ref` triggers,
  keeps fingerprints in the Portal SQLite DB, and passes the Portal-specific
  `RESULT_SERVER` URL to GitLab pipelines so dev Portal triggers return results
  to the same dev Portal.
- Triggered pipelines receive `BK_TRIGGER_ID`, `BK_TRIGGER_TYPE`, and
  `BK_TRIGGER_REASON`. `scripts/result.sh` stores these values under
  `execution_trigger` in Result JSON, and the Portal shows them as the result
  `Run Cause`.
- Received benchmark and estimation JSON metadata is indexed into
  `result_metadata_index` at ingest time. JSON/tgz artifacts remain the raw
  records and existing result pages remain file-backed.
- Generated GitLab CI jobs collect lightweight environment snapshots in the
  common build/run/build_run wrappers, without requiring application
  `build.sh` or `run.sh` changes. Result submission combines those artifacts
  into a Result JSON `environment_snapshot` reference block. The Portal indexes
  the snapshot payload by hash in `environment_snapshots` and links received
  results through `environment_snapshot_results`. Result detail pages show the
  snapshot hash, allocation project ID, scheduler, runner, and Benchkit commit.

Remaining follow-up:

1. Review which result and estimate views should move from file-backed scans to
   indexed lookup once the operational view requirements are stable.
2. Expand environment snapshot collectors only when a specific site needs more
   runtime detail. The v1 collector intentionally avoids full environment dumps
   and secret-bearing CI variables.

GitLab schedules should not be the primary governance point. The Portal should
own periodic and event-triggered execution decisions, then trigger GitLab CI
with resolved site-local variables.

The current GitLab CI entry point consumes `code`, `system`, and the resolved
allocation project ID. Execution profile fields such as `exp` remain
Portal-side matching and audit metadata until the GitLab matrix generator grows
a matching selector. Scheduler-specific command-line formatting belongs to the
Benchkit CI generation layer, not to Portal profile records. Allocation project
ID is optional. Slurm systems that require an explicit charged project, such as
RIKYU, derive `--account=<BK_ALLOCATION_PROJECT_ID>` when the value is present,
unless a site-local `BK_SCHEDULER_EXTRA_ARGS*` override is already set. Systems
without such a scheduler requirement should leave the field empty. Benchpark
bridge controls in this repository are legacy; active Benchpark CI/CD/CB result
handling has moved to a separate project.

Node-hour accounting follows the Result JSON `execution_mode` value. `cross`
results count run time only, because build and run are separated. Systems that
build and run in one scheduler job are recorded as `native`; `native` counts
build time plus run time.

Environment snapshots are result-time evidence, not profile policy. Profiles
describe the intended scope, allocation, approval state, and trigger bindings;
snapshots describe what the CI job actually observed when it packaged the
result. The v1 snapshot identity is the SHA-256 hash of the canonical snapshot
payload assembled from `results/environment_snapshot_build.json`,
`results/environment_snapshot_run.json`, or
`results/environment_snapshot_build_run.json`.

## Profile Request Workflow

Execution profile requests are tracked separately from the approved profile
registry. The applicant-facing page is `/execution-profile-requests/`; it is
available to authenticated users and records the requester from the active
session. The admin review page is `/admin/execution-profile-requests`.

The applicant form intentionally asks only for fields the application side can
reasonably own: application code, system, optional exp/case scope, optional
activity, optional desired schedule, optional desired repo/ref watch target, and
an operational note. Allocation project ID, validity, and trigger conversion are
reviewer responsibilities.

Requests have a `request_type`:

- `new_profile`: creates an approved execution profile after review.
- `change_profile`: updates an existing linked profile after review.
- `pause_profile`: disables the linked profile and its trigger definitions.
- `retire_profile`: marks the linked profile retired and disables its trigger
  definitions.

Pause and retirement are state transitions, not deletes. The profile and request
history remain in the site-local DB so operators can audit what happened and
why. Deleting a profile remains an admin operation outside the applicant request
workflow.

The applicant page shows each request's linked profile, current profile status,
enabled state, allocation project ID, and enabled/total trigger counts when a
profile has been created. Follow-up requests are created from that linked
profile, so the applicant view and the approved registry stay connected after
the initial approval.

## GitLab Pipeline Trigger Configuration

Dry-run payload rendering requires:

```text
RESULT_SERVER_GITLAB_REPO=gitlab.example.org/group/project
```

Actual submission also requires:

```text
RESULT_SERVER_GITLAB_TRIGGER_TOKEN=<site-local GitLab pipeline trigger token>
```

`RESULT_SERVER_GITLAB_REPO` is a scheme-less `host/path` value. The trigger
token must be created for that GitLab project. The Portal records the request
payload, GitLab response metadata, status, and errors in `execution_requests`;
it must not record the token value.

For multiple destinations, configure named targets instead of the single-repo
fallback:

```text
RESULT_SERVER_GITLAB_TARGETS=site_ci=gitlab.example.org/group/project,public_mirror=gitlab.com/group/project
RESULT_SERVER_GITLAB_TRIGGER_TOKEN_SITE_CI=<site-local GitLab pipeline trigger token>
RESULT_SERVER_GITLAB_TRIGGER_TOKEN_PUBLIC_MIRROR=<site-local GitLab pipeline trigger token>
```

Target IDs may contain letters, digits, `_`, `.`, and `-`. The token variable is
`RESULT_SERVER_GITLAB_TRIGGER_TOKEN_<TARGET_ID>` with non-alphanumeric
characters converted to `_` and uppercased. Store these variables in the Portal
systemd `EnvironmentFile`, not in the repository.

## Portal Trigger Runner

Portal-managed scheduled and event triggers are evaluated by a site-local
runner, not by GitLab schedules. Install it as a systemd user timer from the
Portal checkout:

```bash
scripts/site/setup_trigger_runner.sh \
  --site dev \
  --repo-dir /srv/benchkit/checkout \
  --venv /opt/benchkit/venv \
  --db /var/lib/benchkit/dev/cx_portal.sqlite3 \
  --env-file /etc/benchkit/dev.env \
  --result-server-url https://portal.example.org/dev \
  --submit
```

For initial bring-up, omit `--submit` or pass `--dry-run`. In dry-run mode the
runner still records run audit rows and, by default, records repo/ref
fingerprints when `--record-observations` is active through the setup script.
The first observation of a `repo_ref` watch initializes the baseline and does
not submit a pipeline; later fingerprint changes can submit.

Scheduled triggers are de-duplicated by cron due minute. The runner records the
due minute in the trigger run reason and does not submit the same due minute
twice after a successful submission. It also looks back a short window, default
5 minutes, so a slightly delayed timer tick can still catch a missed cron
minute. Tune this with `--schedule-lookback-minutes` if the timer interval is
changed.

The runner uses a short-lived SQLite lock by default so overlapping timer
invocations do not evaluate or submit the same triggers twice. Tune the lock
TTL with `--lock-ttl-seconds` when the timer interval is changed.

The admin execution-profile page shows recent trigger runner decisions,
including `not_due`, `already_submitted`, `unchanged`, `blocked`,
`submitted`, and `submit_failed`. For `repo_ref` watches it also shows the
latest observed target fingerprint. Results produced by Portal-triggered
pipelines show a `Run Cause` column in the results table and a matching detail
row when the Result JSON contains `execution_trigger`.

Routine non-submit decisions such as `not_due`, `unchanged`,
`already_submitted`, and `runner_locked` are rate-limited in `trigger_runs`.
The default interval is 60 minutes, so a one-minute timer does not write a
routine history row on every tick. Use `--routine-log-interval-minutes 0` only
when intentionally debugging every runner tick.
Repo/ref observations are only persisted when a fingerprint is first initialized
or changes; unchanged checks do not update `observed_at` on every timer tick.

The generated service reads GitLab trigger configuration from the
`EnvironmentFile`. The token must remain site-local:

```text
RESULT_SERVER_GITLAB_TARGETS=site_ci=gitlab.example.org/group/project
RESULT_SERVER_GITLAB_TRIGGER_TOKEN_SITE_CI=<site-local GitLab pipeline trigger token>
```

## Compatibility Expectations

Keep the existing `list.csv` and `queue.csv` paths working. Execution profiles
should act as a site-local override or governance layer, not as a replacement
for app participation registration.

`BK_SCHEDULER_EXTRA_ARGS` and `BK_SCHEDULER_EXTRA_ARGS_<SYSTEM>` remain low-level
escape hatches for bring-up and sites that do not yet use Portal execution
profiles. They should not be the primary governance interface once a site uses
Portal-managed profiles and triggers.
