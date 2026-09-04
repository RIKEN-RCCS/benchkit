#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping process_and_send_results test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'chmod -R u+rwX "${TMP_DIR}" 2>/dev/null || true; rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/project/scripts/result_server" "${TMP_DIR}/project/results" "${TMP_DIR}/bin"
cp "${REPO_DIR}/scripts/collect_timing.sh" "${TMP_DIR}/project/scripts/collect_timing.sh"
cp "${REPO_DIR}/scripts/collect_environment_snapshot.sh" "${TMP_DIR}/project/scripts/collect_environment_snapshot.sh"
cp "${REPO_DIR}/scripts/result.sh" "${TMP_DIR}/project/scripts/result.sh"
cp "${REPO_DIR}/scripts/result_server/client_env.sh" "${TMP_DIR}/project/scripts/result_server/client_env.sh"
cp "${REPO_DIR}/scripts/result_server/send_results.sh" "${TMP_DIR}/project/scripts/result_server/send_results.sh"
cp "${REPO_DIR}/scripts/result_server/process_and_send_results.sh" "${TMP_DIR}/project/scripts/result_server/process_and_send_results.sh"

cat > "${TMP_DIR}/project/results/result" <<'EOF'
FOM:1.25 FOM_unit:s FOM_version:test Exp:CASE0 node_count:1 numproc_node:2 nthreads:3
EOF

printf '%s\n' 100 > "${TMP_DIR}/project/results/build_start"
printf '%s\n' 105 > "${TMP_DIR}/project/results/build_end"
printf '%s\n' 110 > "${TMP_DIR}/project/results/run_start"
printf '%s\n' 120 > "${TMP_DIR}/project/results/run_end"
cat > "${TMP_DIR}/project/results/environment_snapshot_run.json" <<'EOF'
{
  "schema_version": 1,
  "stage": "run",
  "collected_at": "2026-08-10T00:00:00Z",
  "system": {
    "name": "Fugaku",
    "allocation_project_id": "rkp00010"
  },
  "scheduler": {
    "kind": "pbs"
  },
  "runner": {
    "description": "fugaku-runner"
  },
  "ci": {
    "pipeline_id": "12345"
  },
  "benchkit": {
    "commit_hash": "abcdef"
  }
}
EOF

cat > "${TMP_DIR}/project/results/input_info.json" <<'EOF'
{
  "schema_version": 1,
  "inputs": [
    {
      "dataset_id": "qws-case0",
      "dataset_version": "2026-09",
      "kind": "benchmark-input",
      "verification_status": "declared"
    }
  ]
}
EOF
build_cache_reason_b64=$(printf '%s' "restored cached build artifacts" | base64 | tr -d '\r\n')
build_cache_ref_b64=$(printf '%s' "develop" | base64 | tr -d '\r\n')
cat > "${TMP_DIR}/project/results/build_cache.env" <<EOF
BK_BUILD_CACHE_STATUS=hit
BK_BUILD_CACHE_REASON_B64=${build_cache_reason_b64}
BK_BUILD_CACHE_DIR_B64=L3RtcC9iZW5jaGtpdC1jYWNoZS9zaG91bGQtbm90LWxlYWs=
BK_BUILD_CACHE_STORED=false
BK_BUILD_CACHE_CREATED_AT=2026-09-04T10:20:30Z
BK_BUILD_CACHE_BUILD_INPUTS_SHA256=1111111111111111111111111111111111111111111111111111111111111111
BK_BUILD_CACHE_SOURCE_INFO_SHA256=2222222222222222222222222222222222222222222222222222222222222222
BK_BUILD_CACHE_ARTIFACTS_SHA256=3333333333333333333333333333333333333333333333333333333333333333
BK_BUILD_CACHE_SOURCE_TYPE=git
BK_BUILD_CACHE_SOURCE_REF_NAME_B64=${build_cache_ref_b64}
BK_BUILD_CACHE_SOURCE_REF_KIND=branch
BK_BUILD_CACHE_SOURCE_RESOLVED_COMMIT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
BK_BUILD_CACHE_CONTAINER_IMAGE_SHA256SUM=4444444444444444444444444444444444444444444444444444444444444444
EOF

cat > "${TMP_DIR}/bin/curl" <<'EOF'
#!/bin/bash
set -euo pipefail
if printf '%s\n' "$*" | grep -q '/api/ingest/result'; then
  printf '%s\n' '{"id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","timestamp":"20260728_070000"}'
  exit 0
fi
printf '%s\n' '{"status":"ok"}'
EOF
chmod +x "${TMP_DIR}/bin/curl"

chmod -R a-w "${TMP_DIR}/project/results"
chmod -R a+rX "${TMP_DIR}/project/results"

export PATH="${TMP_DIR}/bin:${PATH}"
export RESULT_SERVER="https://example.invalid"
export RESULT_SERVER_CLIENT_CERT="${TMP_DIR}/client.crt"
export RESULT_SERVER_CLIENT_KEY="${TMP_DIR}/client.key"
touch "$RESULT_SERVER_CLIENT_CERT" "$RESULT_SERVER_CLIENT_KEY"
export BK_TRIGGER_ID="qws-fugaku-1400"
export BK_TRIGGER_TYPE="scheduled"
export BK_TRIGGER_REASON="cron:0 14 * * *@2026-08-07T14:00+09:00"
export PARENT_PIPELINE_ID="54321"

pushd "${TMP_DIR}/project" >/dev/null
bash scripts/result_server/process_and_send_results.sh qws Fugaku cross qws_Fugaku_build qws_Fugaku_N1_P2_T3_run 12345
popd >/dev/null

test ! -f "${TMP_DIR}/project/results/result0.json"
test -f "${TMP_DIR}/project/send_results_workspace/results/result0.json"
test -f "${TMP_DIR}/project/send_results_workspace/results/server_result_meta.json"
test -f "${TMP_DIR}/project/send_results_workspace/results/pipeline_timing.json"
test -f "${TMP_DIR}/project/send_results_workspace/results/environment_snapshot_run.json"

jq -e '._server_uuid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"' \
  "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '.execution_trigger.id == "qws-fugaku-1400" and .execution_trigger.type == "scheduled"' \
  "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '.pipeline_id == 12345 and .parent_pipeline_id == 54321' \
  "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '
  .environment_snapshot.hash | startswith("sha256:")
' "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '
  .environment_snapshot.summary.system == "Fugaku"
' "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '
  .environment_snapshot.payload.stages.run.stage == "run"
' "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '
  .input_info.schema_version == 1 and
  .input_info.inputs[0].dataset_id == "qws-case0" and
  .input_info.inputs[0].verification_status == "declared"
' "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '
  .build_cache.status == "hit" and
  .build_cache.reason == "restored cached build artifacts" and
  .build_cache.entry.created_at == "2026-09-04T10:20:30Z" and
  .build_cache.entry.digests.build_inputs == "sha256:1111111111111111111111111111111111111111111111111111111111111111" and
  .build_cache.entry.source.ref_name == "develop" and
  .build_cache.entry.container_image.sha256sum == "sha256:4444444444444444444444444444444444444444444444444444444444444444" and
  (.build_cache.hit_basis | index("build inputs hash matched")) and
  ((.build_cache | tostring | contains("should-not-leak")) | not)
' "${TMP_DIR}/project/send_results_workspace/results/result0.json" >/dev/null
jq -e '."result0.json".uuid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"' \
  "${TMP_DIR}/project/send_results_workspace/results/server_result_meta.json" >/dev/null

echo "process_and_send_results read-only artifact test passed"
