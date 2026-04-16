# Developer Reference

This document is intended for CX Framework and BenchKit developers. It collects structural and operational details that are too implementation-focused for the top-level README.

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
  BenchPark integration and conversion support.
- `result_server/`
  Flask-based result portal, ingest API, authentication, admin pages, and tests.
- `scripts/`
  Shared CI helpers, result shaping, estimation helpers, and portal upload scripts.
- `config/`
  System, queue, and hardware metadata.
- `docs/`
  Specifications and operational guides.

## Result Portal

### Overview

`result_server/` provides:

- ingest APIs for results, estimates, profiler archives, and estimation inputs
- public and confidential result views
- detailed result and estimate pages
- usage reporting
- TOTP-based authentication
- admin pages for user management

### Main Route Groups

- `result_server/routes/results.py`
  Result-related blueprint registration.
- `result_server/routes/results_list_routes.py`
  Public and confidential result list pages.
- `result_server/routes/results_detail_routes.py`
  Result detail, compare, downloads, and related views.
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
  Admin-only user management.

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

## 5. BenchPark Integration

- BenchPark-specific conversion and bridge logic lives under `benchpark-bridge/`.
- BenchPark CI can adapt BenchPark-native outputs into the ingest schema used by the result server.

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

### GitHub to GitLab Synchronization

BenchKit uses GitHub for source hosting and GitLab CI for benchmark execution.

### Automatic Skip Rules

To avoid unnecessary benchmark execution, the pipeline skips jobs when changes are limited to:

- `*.md`
- `result_server/**/*`

These rules are defined in [.gitlab-ci.yml](../../.gitlab-ci.yml).

### Execution Control Options

Commit-message and variable-driven controls remain available for benchmark and BenchPark workflows. Refer to `.gitlab-ci.yml` and `benchpark-bridge/scripts/ci_generator.sh` for the active control points.

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
- GitLab CI runner support
- site-specific scheduler/runtime support
- Python for result shaping, estimation support, and portal components
- Flask-related Python packages for `result_server`
- optional profiler tools depending on system support

For local portal work, see the route, template, and utility layout under `result_server/`.
