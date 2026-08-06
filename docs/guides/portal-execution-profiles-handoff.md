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
   pipeline trigger payload without sending it.
5. Add the real GitLab pipeline trigger only after the dry-run path is
   reviewed. Keep the trigger token in the site-local service environment as
   `RESULT_SERVER_GITLAB_TRIGGER_TOKEN`; do not store it in SQLite, logs, or
   the OSS repository.
6. Add a site-local trigger runner timer. The runner should evaluate Portal
   trigger definitions, keep `repo_ref` fingerprints in the Portal SQLite DB,
   and pass the Portal-specific `RESULT_SERVER` URL to GitLab pipelines so
   dev Portal triggers return results to the same dev Portal.
7. Index received benchmark and estimation JSON metadata into SQLite while
   keeping JSON/tgz artifacts as raw records. The first index should be an
   auxiliary lookup table populated at ingest time; existing result and
   estimate pages can remain file-backed until the indexed views are reviewed.
8. Add environment snapshot storage after deciding which host/runtime metadata
   should define an environment identity.

GitLab schedules should not be the primary governance point. The Portal should
own periodic and event-triggered execution decisions, then trigger GitLab CI
with resolved site-local variables.

The current GitLab CI entry point consumes `code`, `system`, BenchPark controls,
and optional scheduler extra args. Execution profile fields such as `exp` remain
Portal-side matching and audit metadata until the GitLab matrix generator grows
a matching selector.

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
RESULT_SERVER_GITLAB_TARGETS=swc=gitlab.swc.example.org/group/project,gitlab_com=gitlab.com/group/project
RESULT_SERVER_GITLAB_TRIGGER_TOKEN_SWC=<site-local GitLab pipeline trigger token>
RESULT_SERVER_GITLAB_TRIGGER_TOKEN_GITLAB_COM=<site-local GitLab pipeline trigger token>
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
  --site dev2 \
  --repo-dir /home/nakamura/ChatGPT/benchkit \
  --venv /home/nakamura/fugakunext/venv \
  --db /home/nakamura/fugakunext/dev2/cx_portal.sqlite3 \
  --env-file /home/nakamura/.config/fncx/dev2.env \
  --result-server-url https://fncx.r-ccs.riken.jp/dev2 \
  --submit
```

For initial bring-up, omit `--submit` or pass `--dry-run`. In dry-run mode the
runner still records run audit rows and, by default, records repo/ref
fingerprints when `--record-observations` is active through the setup script.
The first observation of a `repo_ref` watch initializes the baseline and does
not submit a pipeline; later fingerprint changes can submit.

The runner uses a short-lived SQLite lock by default so overlapping timer
invocations do not evaluate or submit the same triggers twice. Tune the lock
TTL with `--lock-ttl-seconds` when the timer interval is changed.

The generated service reads GitLab trigger configuration from the
`EnvironmentFile`. The token must remain site-local:

```text
RESULT_SERVER_GITLAB_TARGETS=swc=gitlab.swc.example.org/group/project
RESULT_SERVER_GITLAB_TRIGGER_TOKEN_SWC=<site-local GitLab pipeline trigger token>
```

## Compatibility Expectations

Keep the existing `list.csv` and `queue.csv` paths working. Execution profiles
should act as a site-local override or governance layer, not as a replacement
for app participation registration.

`BK_SCHEDULER_EXTRA_ARGS` and `BK_SCHEDULER_EXTRA_ARGS_<SYSTEM>` remain low-level
escape hatches for bring-up and sites that do not yet use Portal execution
profiles.
