# Execution evidence in Runs

Runs can display an explicitly imported observation even when no Result exists.
Import is an offline administrative operation. It does not poll GitLab, contact
a scheduler, submit a pipeline, retry a job, or modify existing Results.

## Meaning of the displayed states

- Submission remains the recorded acceptance decision, not completion.
- CI observed is GitLab's pipeline state at the supplied observation time.
- Unfinished jobs lists observed job stages and states, without inferring a
  stage from a job name. Pipeline state does not establish computation success.
- Compute job ID, start, state and exit code require explicit compute evidence.
  A Runner wait timeout alone does not establish whether computation started
  or ended. Use `null` / `unknown` when not confirmed.
- Stored Results uses the existing, separate Result association. A successful
  delivery job alone never establishes Result storage.

Observation and import timestamps are separate. These are historical snapshots,
not live monitoring. Missing evidence, unavailable storage and unknown compute
facts are distinct. The details page shows at most the latest 20 observations;
older observations remain in encrypted storage. No automatic expiry is applied.

## Explicit import

An existing initialized encrypted CX metadata database and its key file are
required. The importer never initializes, migrates or falls back to plaintext
storage. No schema update or Result index rebuild is necessary.

Run either `python -m result_server.execution_evidence --plan PLAN --input INPUT`
from the repository root, or `python result_server/execution_evidence.py ...`.
Both files must follow the existing private-input rules (private directory,
owner-only regular file, no symlink). The plan has exactly these path fields:

```json
{
  "database": "/private/cx/metadata.db",
  "key_file": "/private/keys/cx.key",
  "artifact_database": "/private/cx/artifacts.db"
}
```

`artifact_database` is optional when the standard sibling filename is used.
Paths must be absolute. Never put key values, tokens, cookies, raw traces or
environment dumps in the plan or evidence. CLI failures report a fixed status,
not exception text, paths, SQL or document contents.

## Observation format, version 1

The input is a normalized observation, not an unfiltered GitLab API response or
an arbitrary `execution.json`. A trusted administrative producer must select
the listed facts from saved pipeline/job observations and execution or Runner
records. It must not fill gaps from a Result's absence or a job's name.
Automatic collection and raw-artifact adapters are not part of this feature.

```json
{
  "version": 1,
  "source": "manual",
  "record_id": 1,
  "project": "gitlab.example.org/team/benchmark",
  "pipeline_id": 42,
  "observed_at": "2026-11-20T01:00:00Z",
  "pipelines": [
    {
      "project": "gitlab.example.org/team/benchmark",
      "id": 42,
      "parent": null,
      "status": "failed"
    }
  ],
  "jobs": [
    {
      "project": "gitlab.example.org/team/benchmark",
      "pipeline_id": 42,
      "id": 90,
      "name": "wait-for-compute",
      "stage": "run",
      "phase": "queue",
      "status": "failed",
      "compute": {
        "scheduler": "batch",
        "job_id": "12345",
        "started": null,
        "status": "unknown",
        "exit_code": null,
        "source": "runner_record",
        "observed_at": "2026-11-20T00:59:00Z"
      }
    }
  ]
}
```

All shown fields are required. Use `compute: null` when no compute record is
available. `source` is `manual` or `runner`; `record_id` is the positive ID in
that submission-history table. IDs from the two tables remain distinct.

Pipeline/job status is one of `created`, `waiting_for_resource`, `preparing`,
`pending`, `running`, `success`, `failed`, `canceled`, `skipped`, `manual`,
`scheduled`. `phase` is an explicit classification from the producer:
`unknown`, `generation`, `build`, `submission`, `queue`, `compute`, `delivery`.
It is not used to guess missing lifecycle facts.

Compute status is `unknown`, `queued`, `running`, `completed`, `failed`,
`canceled`, or `timeout`. `started` is true, false or null. `running` and
`completed` require true; an exit code also requires a recorded start.
`source` is `execution_record`, `runner_record` or `scheduler_record`, identifying
the evidence class. The job/pipeline IDs identify its GitLab context. Imported
facts are assertions by the trusted producer, not independently verified claims.
Do not copy a Runner's own timeout into compute status without compute evidence.

Each child pipeline carries an explicit `parent: {"project": ..., "id": ...}`.
All pipelines must connect to the recorded root, with no cycles or duplicates.
Every job must belong to one of these pipelines. A host-qualified project is
mandatory at every level; equal pipeline/job numbers on different hosts or
projects do not establish identity. URLs are constructed from validated
identities, never accepted from the input.

The root must exactly match an existing submitted, non-preview history record.
Unknown fields, duplicate JSON keys, control characters, unsafe project paths,
invalid types, disconnected graphs and contradictory start facts are rejected.
Limits: 1 MiB input, 128 pipelines, 1,024 jobs, 160 characters per job name or
stage, 512 per project, 128 per compute job ID. Timestamps require an explicit
timezone and are normalized to UTC. Compute observations cannot follow their
enclosing observation.

## Consistency and access

Import uses one transaction for history binding, immutable observation insertion
and latest-observation update. Re-importing the same observation is idempotent.
Different content at the same observation time is rejected. Older observations
are retained but do not replace the latest observation. Existing encrypted
metadata backups include both current and historical evidence automatically.

Runs reads only a bounded page of local evidence in a single read connection;
the details page does not scan Results. Profile editing and dry-run do not wait
for evidence or Result resolution. Evidence details share the existing admin
authorization boundary; there is no new public or remote ingestion endpoint.
Enabling storage, selecting a trusted producer and an operational retention
policy remain explicit administrative decisions, not application startup work.
