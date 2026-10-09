# Developer Reference

This document is intended for CX Framework and Benchkit developers. It collects structural and operational details that are too implementation-focused for the top-level README.

## Project Structure

```text
benchkit/
|- programs/
|  `- <code>/
|     |- build.sh
|     |- run.sh
|     |- estimate.sh
|     `- list.csv
|- benchpark-bridge/
|  |- config/
|  `- scripts/
|- result_server/
|  |- routes/
|  |- templates/
|  |- utils/
|  |- tests/
|  |- app.py
|  |- app_dev.py
|  `- create_admin.py
|- scripts/
|  |- result_server/
|  `- estimation/
|- config/
|- docs/
|  |- cx/
|  `- guides/
`- .gitlab-ci.yml
```

### Key Areas

- `programs/<code>/`
  App-specific build, run, and estimation entry points.
- `benchpark-bridge/`
  Legacy Benchpark bridge and conversion support. Active Benchpark CI/CD/CB
  result handling has moved to a separate project.
- `result_server/`
  Flask-based result portal, ingest API, authentication, admin pages, and tests.
- `scripts/`
  Shared CI helpers, result shaping, estimation helpers, and portal upload scripts.
- `config/`
  System, queue, and hardware metadata.
- `docs/`
  Specifications and operational guides.

## Contributor Responsibility Boundaries

The current repository workflow uses the following responsibility split.
These are working roles for repository changes and reviews, not a full portal-side approval workflow.
A future "requester" or "applicant" role belongs to the not-yet-implemented request/approval workflow.

| Role | Owns | Usually edits |
|---|---|---|
| App maintainer | App-specific build, run, result emission, app-side estimation declarations, and app-local test cases. | `programs/<code>/build.sh`, `programs/<code>/run.sh`, `programs/<code>/estimate.sh`, `programs/<code>/list.csv` |
| Site maintainer | System registration, queue/scheduler settings, runner setup assumptions, and portal display metadata for systems. | `config/system.csv`, `config/queue.csv`, `config/system_info.csv`, [add-site.md](./add-site.md) |
| Estimation package maintainer | Estimation algorithm, required inputs, metadata, applicability, fallback, and package-specific assumptions. | `scripts/estimation/packages/`, `scripts/estimation/section_packages/`, [add-estimation-package.md](./add-estimation-package.md) |
| Benchkit common maintainer | Shared shell helpers, Result/Estimate JSON handoff, portal implementation, common CI checks, and repository-wide contracts. | `scripts/bk_functions.sh`, `scripts/result.sh`, `scripts/estimation/common.sh`, `scripts/result_server/`, `result_server/`, `.github/`, `.gitlab-ci.yml` |
| Admin / reviewer / approver | Review, manual CI judgment, PR acceptance, and portal admin operations. In the current workflow these are the same operational role. | GitHub PRs, GitLab manual CI, portal admin pages |

Scaffolding or code generation may be added later as convenience tooling, but it is not required for contributors.
The supported baseline is that contributors can add apps, sites, and estimation packages by following the guides and existing examples.

## Result Portal

### Overview

`result_server/` provides:

- ingest APIs for results, estimates, profiler archives, and estimation artifacts
- public and confidential result views
- detailed result and estimate pages
- usage reporting
- TOTP-based authentication
- admin pages for user management, execution profile governance, Portal-managed
  GitLab trigger submission, trigger-runner observations, and related operation
  history

### Main Route Groups

- `result_server/routes/results.py`
  Result-related blueprint registration.
- `result_server/routes/results_list_routes.py`
  Public and confidential result list pages.
- `result_server/routes/results_detail_routes.py`
  Result detail, compare, evidence packet, public reuse packet, public reuse
  manifest, downloads, and related views.
- `result_server/routes/results_usage_routes.py`
  Usage reporting pages.
- `result_server/routes/estimated.py`
  Estimated-result blueprint registration.
- `result_server/routes/estimated_list_routes.py`
  Estimated-result list pages.
- `result_server/routes/estimated_detail_routes.py`
  Estimated-result detail and downloads.
- `result_server/routes/api.py`
  Ingest and query APIs.
- `result_server/routes/auth.py`
  Login, setup, logout, and TOTP flow.
- `result_server/routes/admin.py`
  Admin-only user management, execution profile registry, manual GitLab trigger
  submission, trigger definitions, trigger run history, and runner observations.

### Main API Endpoints

The canonical estimation artifact endpoints are:

- `POST /api/ingest/estimation-artifacts`
  Upload a lightweight estimation artifact bundle associated with a source result UUID.
- `GET /api/query/estimation-artifacts?uuid=<source_result_uuid>`
  Download the stored estimation artifact bundle for re-estimation.

The older `estimation-inputs` endpoint names remain as compatibility aliases
only. New client code and documentation should use `estimation-artifacts`.
Estimation artifact bundles may contain prepared estimator inputs, prediction
outputs, and logs, but should not duplicate large profiler archives such as PA
Data or `*.ncu-rep`.

### Main Templates

- `result_server/templates/_results_base.html`
  Shared shell for portal pages.
- `result_server/templates/_table_base.html`
  Shared table page base.
- `result_server/templates/results.html`
  Result list page.
- `result_server/templates/result_detail.html`
  Result detail page.
- `result_server/templates/result_compare.html`
  Result comparison page.
- `result_server/templates/estimated_results.html`
  Estimated-result list page.
- `result_server/templates/estimated_detail.html`
  Estimated-result detail page.
- `result_server/templates/usage_report.html`
  Usage report page.
- `result_server/templates/systemlist.html`
  System list page.
- `result_server/templates/auth_login.html`
  Login page.
- `result_server/templates/auth_setup.html`
  TOTP setup page.
- `result_server/templates/admin_users.html`
  Admin user management page.
- `result_server/templates/admin_execution_profiles.html`
  Admin execution profile, trigger definition, trigger run, and observation page.

## CI Pipeline Structure

## 1. Main Pipeline

- Reads `programs/<code>/list.csv`, `config/system.csv`, and `config/queue.csv`
- Generates `.gitlab-ci.generated.yml` with `scripts/matrix_generate.sh`
- Supports both cross-build and native execution modes
- Enables or disables jobs based on `list.csv`

## 2. Benchmark Execution Pipelines

### Cross mode

- `build`
- `run`
- `send_results`

### Native mode

- `build_run`
- `send_results`

### Common Notes

- `build.sh` and `run.sh` are the primary application entry points.
- `run.sh` receives `system`, `nodes`, `numproc_node`, and `nthreads`.
- `scripts/bk_functions.sh` provides shared emit helpers such as result, section, and overlap output.
- `record_timestamp.sh`, `collect_timing.sh`, and `result.sh` shape timing and result JSON data before upload.

## 3. Result Transfer and Storage

- `scripts/result_server/send_results.sh`
  Uploads result JSON and profiler archives.
- `scripts/result_server/send_estimate.sh`
  Uploads estimated-result JSON.
- `scripts/result_server/fetch_result_by_uuid.sh`
  Fetches uploaded result data by UUID.

## 4. Estimation Pipeline

- App-specific estimation logic lives in `programs/<code>/estimate.sh`.
- Shared helpers live under `scripts/estimation/`.
- Re-estimation uses result UUIDs as the main input contract.

## 5. Benchpark Integration

- Legacy Benchpark-specific conversion and bridge logic remains under
  `benchpark-bridge/`.
- Active Benchpark CI/CD/CB result handling is maintained in a separate project. Treat this repository's bridge as legacy and QC-GH200-oriented unless a
  future PR explicitly reworks it.

## Configuration Files

- `config/system.csv`
  System execution configuration.
- `config/queue.csv`
  Queue configuration.
- `config/system_info.csv`
  Hardware and display metadata for the portal.
- `programs/<code>/list.csv`
  App-specific execution matrix.

## CI Execution Control

Benchkit uses GitHub for source hosting and GitLab CI for benchmark execution.

The current policy keeps pull requests lightweight. Heavy GitLab benchmark CI is not started automatically for pull requests or protected-branch synchronization; maintainers start it explicitly through GitHub Actions when needed.

See [CI Execution Control / CI実行制御](../ci.md) for the active workflow policy, manual GitLab CI inputs, protected-branch synchronization behavior, and legacy commit-message controls.

## System-Specific Execution Environments

Execution environments are controlled by:

- `config/system.csv`
- `config/queue.csv`
- per-app `list.csv`
- app-specific `build.sh` and `run.sh`

Each system can define queue group, build mode, run mode, node count, and related scheduler settings.

## Runtime Requirements

Typical requirements include:

- Bash and standard shell tooling
- GNU coreutils, GNU findutils, and `flock` (util-linux) for common log collection
  and session initialization
- GNU `date` with `%s`/`%N` support and `awk` for command elapsed time
- GitLab CI runner support
- site-specific scheduler/runtime support
- `jq` and `curl` on the result sender, not on common build/run paths
- Python 3.12 or later for Result Server and Portal components
- Flask-related Python packages for `result_server`
- package-specific runtimes for external estimation tools
- optional profiler tools depending on system support

### Input and Execution Evidence

Input collection records actual content, not an execution allowlist. Changed
inputs, unavailable observations and application failures are distinct states.
`collection_status` is `recorded` or `unavailable`; unavailable observations
include a bounded `collection_error` code and no fabricated digest. Declared
dataset versions remain labels, not substitutes for an observed content digest.

Existing `--expected-manifest` calls perform informational comparison only:
`verification_status` is `verified` for a match, `mismatch` for different content,
or `unavailable` if the reference cannot be read or validated. Actual content is
recorded independently. References retain the manifest schema with integer
`schema_version: 1`, `kind`, and `files` containing relative `path`, nonnegative
`size_bytes`, and full lowercase `sha256`; duplicate keys are invalid. The legacy
`--verify-file` / `--expected-sha256` / `--expected-size-bytes` trio also records
differences instead of rejecting execution. Invalid call syntax remains an error.

Collection is bounded to 10,000 entries, 64 directory levels and a 4 MiB manifest.
External nested symlinks, cycles, special files and detected concurrent changes
cannot produce a complete observation. Metadata destinations must remain outside
the input; this safety constraint is separate from content comparison.

Generated run/build-run jobs retain `results/` artifacts on failure. The common
run wrapper writes `execution.json` and `execution.log`, preserving the application
exit code even when metadata storage fails. A forcibly interrupted wrapper can
leave a `running` record; this is not evidence of success. Logged commands retain
their output even if subsequent FOM extraction fails. The CI-only filename
`execution-output_<scope>_<stage-id>.log` associates each log with its
`workflow_timing_<scope>.json` record and stage ID. If the timing recorder is
unavailable, a uniquely named log is retained without claiming an association.
Source and environment records remain alongside these artifacts. No FOM or successful
Result is invented for failed or FOM-less runs; these execution records remain CI
evidence, not new Portal result rows. Access to CI logs/artifacts must be restricted
appropriately; they can contain application output and are not public metadata.

### Runtime Details

Command timing, input capture and execution/profile association use Bash and
standard shell tools on compute nodes, without Python, `jq` or `curl`.
File content is streamed once into SHA-256 and byte counting; source bytes are
not copied into artifacts. Bounded file inventories before and after collection
detect changes. The result sender uses `jq` to finalize the canonical manifest,
content digest and dataset version, and merge inputs from current-session,
experiment-bound workflow records. It leaves the original execution artifacts
unchanged. Applications continue using the same input and execution helpers.
Intermediate items carry an `observation_capture` with per-file hashes and
collection status; finalized Result inputs retain the existing manifest/digest
fields. Unbound or older-session records remain CI evidence, not Result inputs.

Optional expected manifests are bounded private companions under
`results/.input_references/`; public observation artifacts carry only an opaque
reference, not reference contents or source locations. The sender validates the
reference before informational comparison and never exports malformed content.
CI artifact access controls must protect these companions, just as execution
logs; a dot-prefixed directory alone does not make its contents private. Do not
include them in public artifact bundles.
Unavailable reference observations do not discard the actual input manifest.
NCU planning retains its separate Python runtime. Acquisition metadata uses
shell JSON output: `gpu_kernel_profile_metadata` schema 2 preserves discovery
text in `nsys_discovery_json`, alongside typed launch-window fields. Estimation
consumers validate and normalize it to the schema-1 object form in memory,
retaining support for existing metadata without rewriting artifacts. Invalid
discovery metadata produces a warning and is not attached to estimates; the
collected profile remains available. This does not change kernel selection or
estimation algorithms.

Elapsed time uses two realtime clock samples immediately around the command,
outside record serialization and lock acquisition. Records identify this as
`elapsed_clock: realtime` and `elapsed_scope: command`; `command_started_at`
is the first sample, while `started_at` records stage preparation. Negative
elapsed time or unsupported clock output is rejected. Forward clock adjustments
cannot be distinguished from execution time; decimal output digits do not
guarantee clock accuracy. Earlier monotonic records included some recorder
overhead and must not be assumed to have identical measurement boundaries.

Common workflow requirements do not restrict application-specific languages or
tools. Applications may use dependencies verified on their target build/run
paths. A tool available on one site's application path must not be assumed to
exist on every runner by common code.

For local portal work, see the route, template, and utility layout under `result_server/`.

### Result Portal Local Test Workflow

For the lightweight `result_server` verification path:

- install dependencies with `python -m pip install -r requirements-result-server.txt`
- run the portal test suite with `python result_server/tests/run_result_server_tests.py`
- CI coverage for portal-only changes is provided by `.github/workflows/result-server-tests.yml`

For production portal deployments:

- Set `FLASK_SECRET_KEY` to a strong secret and run `result_server/app.py`, not `app_dev.py`.
- `app.py` binds to `127.0.0.1:8800` by default; set `RESULT_SERVER_HOST` and `RESULT_SERVER_PORT` explicitly when the deployment requires a different bind address.
- For built-in upload/query helper scripts, use mTLS with `RESULT_SERVER_CLIENT_CERT` and `RESULT_SERVER_CLIENT_KEY`; they do not send an `X-API-Key` header.
- `RESULT_SERVER_KEYS=runner-a:<RUNNER_A_KEY>,runner-b:<RUNNER_B_KEY>` remains a server-side registry for legacy or custom clients that still send `X-API-Key`.
- `FLASK_SECRET_KEY` and each ingest key must be at least 32 characters and must not use known insecure examples such as `dev-api-key`, `changeme`, or `secret`; production startup refuses these values.
- The legacy server-side `RESULT_SERVER_KEY` variable is still accepted as runner `default` for compatibility, but production portal deployments should rotate the accepted-key registry to `RESULT_SERVER_KEYS`.
- See `docs/deploy/key-management.md` for generation and rotation guidance.
- `REDIS_URL` must point to a monitored Redis instance; production authentication refuses login when Redis is unavailable.
- Login verification, API ingest/query, and admin write endpoints use Redis-backed rate limits by default; set `RESULT_SERVER_MAX_UPLOAD_MB` and `RESULT_SERVER_MAX_ARCHIVE_MEMBER_MB` when deployment-specific upload limits are needed.
- Repeated login failures are tracked per email for audit context only; source-scoped Redis rate limits enforce login traffic control without hard-locking a target account.
- Admin-managed affiliations are only rejected when they contain unsafe path/control characters or the comma delimiter used by the form; set `RESULT_SERVER_ALLOWED_AFFILIATIONS` only when a deployment wants to enforce a fixed comma-separated allowlist.
- Security-relevant auth, API, and admin actions emit structured `benchkit.audit` events; see `docs/cx/AUDIT_LOG_SPEC.md`.
- `app_dev.py` is localhost-only, uses ephemeral development secrets when none are provided, and enables the Werkzeug debugger only with `RESULT_SERVER_DEV_DEBUG=1`.

### Result Quality Visibility

Benchkit keeps result-quality scoring inside the portal. Normal pull requests should not be blocked on quality scoring beyond producing valid result JSON with a FOM value.

Portal quality visibility currently lives in:

- result list quality badges
- result detail quality rows
- `/results/usage` current-state quality summaries

Treat missing `source_info`, `fom_breakdown`, or artifact references as follow-up improvement candidates, not upload-time or pull-request gates.
Detailed timing artifacts may be recorded through `timing_observations` before
they are promoted to `fom_breakdown`; do not treat every detailed timer or
profiler region as an additive estimation section without an app-specific
mapping review. Apps should use `bk_record_timing_observation` for this
handoff. Referenced `results/*.json` timing files and profiler archives are
uploaded as Measurement Artifacts by the result sender.

Detailed timing registration stores an internal `timing_capture` snapshot using
shell commands. The sender validates this JSON, derives optional summary fields,
and removes the capture from the public Result. Explicit registration fields take
precedence over artifact defaults. Invalid captures are diagnosed and omitted
without dropping the FOM or valid observations. Existing normalized observations
remain supported. Application parsers retain ownership of timer interpretation
and their own runtime dependencies.
