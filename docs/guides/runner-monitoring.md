# Runner observations

The console's **Runners** view is read-only and restricted to current CX
administrators. Public portals do not expose it. It reads an encrypted snapshot,
not GitLab on each page request. Budget settings and execution permissions are
not changed by monitoring.

## Connections and Identity

Use the existing `RESULT_SERVER_GITLAB_TARGETS` definitions. Configure dedicated
API read credentials separately in `RESULT_SERVER_RUNNER_MONITOR_TARGETS`, a JSON
object keyed by an existing target ID. For example:

```json
{
  "example": {
    "token_file": "/example/credentials/runner-read.token",
    "runner_types": ["instance_type", "group_type", "project_type"]
  }
}
```

The path is illustrative. Store each credential as one line in a regular file
owned by the collector user with mode 600, inside a private mode-700 directory.
Symlinks and hard links are rejected. Never put token values in the repository,
command arguments, logs, or this JSON setting. Trigger and runner authentication
tokens are not monitoring credentials; no fallback to them is performed.

Use the least privileges that allow the required project runner reads. A token
with `read_api` still needs sufficient project membership. Check inventory,
detail, and manager endpoints separately; permissions can differ. See the
[GitLab Runners API](https://docs.gitlab.com/api/runners/).

Runner identity is the normalized GitLab server plus runner ID, not a tag or
project. Inventories are read independently for each project; successful shared
runner detail/manager reads are reused within a collection. Another associated
project credential can retry a failed read on the same server. Requests are GET
only, use TLS verification, and refuse redirects. Response fields are allowlisted;
IP addresses and raw API responses are not persisted.

`runner_types` defaults to all three types. To omit hosted instance runners from
a connection, explicitly choose `group_type` and `project_type`. The view shows
the configured scope. Changing scope or project identity invalidates that
connection's previous inventory. A successful complete inventory removes missing
relationships; an incomplete or failed inventory preserves the last success.

## Encrypted Storage

Install the SQLCipher dependency from `requirements-budget-db.txt`. Use a
dedicated observation database and key, separate from the Budget registry.
The web application never creates or migrates the database at startup.
Create private parent directories first; keep the key outside the DB directory.

Configure the collector and authorized console with:

- `RESULT_SERVER_RUNNER_MONITOR_DB_PATH`: observation database path.
- `RESULT_SERVER_RUNNER_MONITOR_KEY_FILE`: 32-byte encryption key file path.

Run the explicit lifecycle commands using those settings:

```bash
python -m result_server.runner_monitor generate-key
python -m result_server.runner_monitor init
python -m result_server.runner_monitor check
python -m result_server.runner_monitor collect
python -m result_server.runner_monitor backup --destination "$BACKUP_PATH"
```

Initialization and key generation never overwrite existing files. Backups remain
encrypted and do not copy the key. Keep recovery keys separately and test recovery.
Encryption protects copied storage, not access by a process holding the key.

## Collection and Display

Schedule `collect` once per shared database, for example every five minutes.
Do not start a collector per web worker or per console. A file lock excludes
overlapping collectors. Network reads have a shared time budget; a completed
snapshot is committed atomically, leaving readers on the preceding snapshot
until then. Partial observation failures are stored and produce exit status 1;
the scheduler must continue future attempts. A five-minute timer should allow
more than the 240-second network budget for committing failures and process exit.

The view separates GitLab heartbeat, paused scheduling, inventory availability,
runner detail availability, and manager availability. It shows last attempt and
last success in expandable rows; the compact list shows runner name, status,
connections, up to two tags, and relative time since the last successful read.
Additional tags, exact timestamps, IDs, and manager information remain in the
expanded detail. Observation warnings remain visible while rows are collapsed.
After fifteen minutes, observations are marked out of date and no
longer claim a current heartbeat or scheduling state. Errors likewise do not
turn the last known online state into a current success, or imply an offline
runner. This snapshot stores the latest observation and preceding successful
data, not a time-series history.

Manager platform/version/contact information describes the runner process, not
the HPC execution node, scheduler allocation authorization, or proof that a job
can finish. Tags are selection conditions, not unique runner identifiers.
Notifications, runner writes, and automatic Budget/trigger changes are not part
of this feature.

## Budget Tag Choices

The CX administrator's Budget editor offers observed runner/tag pairs for the
selected GitLab connection. Matching requires the same server and project, and
the target ID for configured connections. Shared runners appear once per
connection. Choosing a candidate copies its tag into the build or run tag field;
it does not save a runner ID or restrict execution to that runner. Matching
runner counts refer only to the observed inventory, not all eligible runners.

Expired or failed inventory/detail observations cannot supply selectable tags.
Offline, paused, and protected runners remain explicitly labelled: their tags
may be configured, but observation does not establish scheduling eligibility,
system suitability, or allocation access. Manual tags remain available when
monitoring is unavailable. Changing connections does not replace existing tags.
Changes still require review and confirmation through the Budget registry;
monitoring never updates saved settings or connects them to triggers automatically.
