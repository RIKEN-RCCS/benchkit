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
jq -e '."result0.json".uuid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"' \
  "${TMP_DIR}/project/send_results_workspace/results/server_result_meta.json" >/dev/null

echo "process_and_send_results read-only artifact test passed"
