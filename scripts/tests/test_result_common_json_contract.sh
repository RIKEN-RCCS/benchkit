#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping result common JSON contract test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/results"

cat > "${TMP_DIR}/results/result" <<'EOF'
FOM:1.25 FOM_unit:s FOM_version:contract-v1 Exp:CASE0 node_count:2 numproc_node:4 nthreads:8 description:smoke confidential:false
SECTION:solve time:1.0
SECTION:io time:0.25
OVERLAP:solve,io time:0.10
EOF

cat > "${TMP_DIR}/results/source_info.env" <<'EOF'
BK_SOURCE_TYPE=git
BK_REPO_URL=https://example.test/demoapp.git
BK_BRANCH=main
BK_COMMIT_HASH=abcdef1234567890
BK_SOURCE_REF_NAME=main
BK_SOURCE_REF_KIND=branch
BK_SOURCE_RESOLVED_COMMIT=abcdef1234567890abcdef1234567890abcdef12
EOF

cat > "${TMP_DIR}/results/input_info.json" <<'EOF'
{
  "schema_version": 1,
  "inputs": [
    {
      "dataset_id": "demo-case0",
      "dataset_version": "2026-09",
      "kind": "repo-local-input",
      "verification_status": "covered_by_source_commit",
      "repo_relative_path": "inputs/demo-case0"
    }
  ]
}
EOF

cat > "${TMP_DIR}/results/pipeline_timing.json" <<'EOF'
{
  "build_time": "12",
  "queue_time": 0,
  "queue_time_source": "not_measured",
  "scheduler_queue_time": 45,
  "scheduler_queue_time_source": "runner_metadata",
  "run_time": 34
}
EOF

cat > "${TMP_DIR}/results/environment_snapshot_build.json" <<'EOF'
{
  "schema_version": 1,
  "stage": "build",
  "collected_at": "2026-09-07T00:00:00Z",
  "system": {
    "name": "DemoSystem"
  },
  "scheduler": {
    "kind": "batch"
  },
  "runner": {
    "description": "demo-runner"
  },
  "ci": {
    "pipeline_id": "4242"
  },
  "benchkit": {
    "commit_hash": "deadbeef"
  },
  "toolchain": {
    "compiler": {
      "version": "demo-compiler 1.0"
    }
  }
}
EOF

cat > "${TMP_DIR}/results/environment_snapshot_run.json" <<'EOF'
{
  "schema_version": 1,
  "stage": "run",
  "collected_at": "2026-09-07T00:01:00Z",
  "system": {
    "name": "DemoSystem"
  },
  "scheduler": {
    "kind": "batch"
  },
  "runner": {
    "description": "demo-runner"
  },
  "ci": {
    "pipeline_id": "4242"
  },
  "benchkit": {
    "commit_hash": "deadbeef"
  }
}
EOF

cat > "${TMP_DIR}/results/build_cache.env" <<'EOF'
BK_BUILD_CACHE_STATUS=hit
BK_BUILD_CACHE_REASON=restored cached build artifacts
BK_BUILD_CACHE_STORED=false
BK_BUILD_CACHE_CREATED_AT=2026-09-07T00:02:00Z
BK_BUILD_CACHE_BUILD_INPUTS_SHA256=1111111111111111111111111111111111111111111111111111111111111111
BK_BUILD_CACHE_SOURCE_INFO_SHA256=2222222222222222222222222222222222222222222222222222222222222222
BK_BUILD_CACHE_ARTIFACTS_SHA256=3333333333333333333333333333333333333333333333333333333333333333
BK_BUILD_CACHE_SOURCE_TYPE=git
BK_BUILD_CACHE_SOURCE_REF_NAME=main
BK_BUILD_CACHE_SOURCE_REF_KIND=branch
BK_BUILD_CACHE_SOURCE_RESOLVED_COMMIT=abcdef1234567890abcdef1234567890abcdef12
BK_BUILD_CACHE_HOST_ENV_FINGERPRINT=4444444444444444444444444444444444444444444444444444444444444444
EOF

pushd "${TMP_DIR}" >/dev/null
export BK_TRIGGER_ID="demoapp-demosystem-watch"
export BK_TRIGGER_TYPE="watch_event"
export BK_TRIGGER_REASON="repo_ref:https://example.test/demoapp.git@main"
export PARENT_PIPELINE_ID="4000"
bash "${REPO_DIR}/scripts/result.sh" demoapp DemoSystem cross demoapp_DemoSystem_build demoapp_DemoSystem_run 4242 >/dev/null
popd >/dev/null

RESULT_JSON="${TMP_DIR}/results/result0.json"
test -f "${RESULT_JSON}"

jq -e '
  type == "object" and
  .code == "demoapp" and
  .system == "DemoSystem" and
  .FOM == "1.25" and
  .FOM_unit == "s" and
  .FOM_version == "contract-v1" and
  .Exp == "CASE0" and
  .node_count == "2" and
  .numproc_node == "4" and
  .nthreads == "8" and
  .description == "smoke" and
  .confidential == "false" and
  .execution_mode == "cross" and
  .ci_trigger == "unknown" and
  .build_job == "demoapp_DemoSystem_build" and
  .run_job == "demoapp_DemoSystem_run" and
  .pipeline_id == 4242 and
  .parent_pipeline_id == 4000
' "${RESULT_JSON}" >/dev/null

jq -e '
  .source_info.source_type == "git" and
  .source_info.repo_url == "https://example.test/demoapp.git" and
  .source_info.ref_name == "main" and
  .source_info.ref_kind == "branch" and
  .source_info.resolved_commit == "abcdef1234567890abcdef1234567890abcdef12" and
  .input_info.schema_version == 1 and
  .input_info.inputs[0].dataset_id == "demo-case0" and
  .input_info.inputs[0].verification_status == "covered_by_source_commit" and
  .pipeline_timing.build_time == 12 and
  .pipeline_timing.queue_time == 0 and
  .pipeline_timing.queue_time_source == "not_measured" and
  .pipeline_timing.scheduler_queue_time == 45 and
  .pipeline_timing.scheduler_queue_time_source == "runner_metadata" and
  .pipeline_timing.run_time == 34 and
  .pipeline_timing.run_time_scope == "job" and
  (.pipeline_timing | has("profiled_run_included") | not)
' "${RESULT_JSON}" >/dev/null

jq -e '
  .fom_breakdown.sections[0].name == "solve" and
  .fom_breakdown.sections[0].time == 1 and
  .fom_breakdown.sections[1].name == "io" and
  (.fom_breakdown.overlaps[0].sections | index("solve") != null) and
  (.fom_breakdown.overlaps[0].sections | index("io") != null)
' "${RESULT_JSON}" >/dev/null

jq -e '
  .environment_snapshot.schema_version == 1 and
  (.environment_snapshot.hash | startswith("sha256:")) and
  .environment_snapshot.summary.system == "DemoSystem" and
  .environment_snapshot.summary.scheduler == "batch" and
  .environment_snapshot.summary.runner == "demo-runner" and
  .environment_snapshot.summary.ci_pipeline_id == "4242" and
  .environment_snapshot.summary.benchkit_commit == "deadbeef" and
  .environment_snapshot.payload.stages.build.stage == "build" and
  .environment_snapshot.payload.stages.run.stage == "run"
' "${RESULT_JSON}" >/dev/null

jq -e '
  .build_cache.schema_version == 1 and
  .build_cache.status == "hit" and
  .build_cache.stored == false and
  .build_cache.reason == "restored cached build artifacts" and
  .build_cache.entry.created_at == "2026-09-07T00:02:00Z" and
  .build_cache.entry.digests.build_inputs == "sha256:1111111111111111111111111111111111111111111111111111111111111111" and
  .build_cache.entry.digests.source_info == "sha256:2222222222222222222222222222222222222222222222222222222222222222" and
  .build_cache.entry.digests.artifacts == "sha256:3333333333333333333333333333333333333333333333333333333333333333" and
  .build_cache.entry.host_environment_fingerprint == "sha256:4444444444444444444444444444444444444444444444444444444444444444" and
  (.build_cache.hit_basis | index("build inputs hash matched") != null) and
  (.build_cache.hit_basis | index("source_info.env digest matched") != null) and
  (.build_cache.hit_basis | index("artifact tree digest matched before and after restore") != null) and
  (.build_cache.hit_basis | index("git source ref resolved to cached commit") != null) and
  (.build_cache.hit_basis | index("host build environment fingerprint matched") != null)
' "${RESULT_JSON}" >/dev/null

jq -e '
  .execution_trigger.id == "demoapp-demosystem-watch" and
  .execution_trigger.type == "watch_event" and
  .execution_trigger.reason == "repo_ref:https://example.test/demoapp.git@main"
' "${RESULT_JSON}" >/dev/null

echo "result common JSON contract test passed"
