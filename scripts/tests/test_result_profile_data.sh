#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/results" "${TMP_DIR}/bk_profiler_artifact" "${TMP_DIR}/ncu/results" "${TMP_DIR}/ncu/bk_profiler_artifact"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping result profile_data test"
  exit 0
fi

cat > "${TMP_DIR}/results/result" <<'EOF'
FOM:9.9999999999999995e-07 FOM_version:test Exp:CASE0 node_count:1 numproc_node:1 nthreads:2
EOF

cat > "${TMP_DIR}/results/pipeline_timing.json" <<'EOF'
{
  "build_time": "12",
  "queue_time": 0,
  "run_time": 34
}
EOF

cat > "${TMP_DIR}/results/timing.env" <<'EOF'
BUILD_TIME=$(touch timing_env_was_sourced)
QUEUE_TIME=999
RUN_TIME=999
EOF

cat > "${TMP_DIR}/bk_profiler_artifact/meta.json" <<'EOF'
{
  "tool": "fapp",
  "level": "single",
  "report_format": "text",
  "raw_dir": "raw",
  "runs": [
    {
      "name": "rep1",
      "event": "pa1",
      "raw_path": "raw/rep1",
      "reports": [
        {"kind": "summary_text", "path": "reports/fapp_A_rep1.txt"}
      ]
    }
  ]
}
EOF

tar -czf "${TMP_DIR}/results/padata0.tgz" -C "${TMP_DIR}" bk_profiler_artifact

cat > "${TMP_DIR}/ncu/results/result" <<'EOF'
FOM:2.345 FOM_version:test Exp:CASE0 node_count:1 numproc_node:8 nthreads:9
EOF

cat > "${TMP_DIR}/ncu/bk_profiler_artifact/meta.json" <<'EOF'
{
  "tool": "ncu",
  "level": "single",
  "report_format": "text",
  "raw_dir": "raw",
  "measurement": {
    "ncu_options": ["--target-processes", "all", "--set", "basic", "--launch-count", "1"]
  },
  "runs": [
    {
      "name": "rep1",
      "event": "single",
      "raw_path": "raw/rep1",
      "reports": [
        {"kind": "ncu_report", "path": "raw/rep1/profile.ncu-rep"},
        {"kind": "summary_text", "path": "reports/ncu_import_rep1.txt"}
      ]
    }
  ]
}
EOF

tar -czf "${TMP_DIR}/ncu/results/padata0.tgz" -C "${TMP_DIR}/ncu" bk_profiler_artifact

pushd "${TMP_DIR}" >/dev/null
bash "${REPO_DIR}/scripts/result.sh" qws Fugaku cross build run 999 >/dev/null
popd >/dev/null

pushd "${TMP_DIR}/ncu" >/dev/null
bash "${REPO_DIR}/scripts/result.sh" genesis RC_GH200 cross build run 999 >/dev/null
popd >/dev/null

RESULT_JSON="${TMP_DIR}/results/result0.json"
test -f "${RESULT_JSON}"
jq -e '
  .FOM == "9.9999999999999995e-07" and
  .profile_data.tool == "fapp" and
  .profile_data.level == "single" and
  .profile_data.report_format == "text" and
  .profile_data.run_count == 1 and
  .pipeline_timing.build_time == 12 and
  .pipeline_timing.queue_time == 0 and
  .pipeline_timing.run_time == 34 and
  (.profile_data.events | index("pa1") != null) and
  (.profile_data.report_kinds | index("summary_text") != null)
' "${RESULT_JSON}" >/dev/null
test ! -f "${TMP_DIR}/timing_env_was_sourced"

NCU_RESULT_JSON="${TMP_DIR}/ncu/results/result0.json"
test -f "${NCU_RESULT_JSON}"
jq -e '
  .profile_data.tool == "ncu" and
  .profile_data.level == "single" and
  .profile_data.report_format == "text" and
  .profile_data.run_count == 1 and
  .profile_data.events == [] and
  (.profile_data.ncu_options | index("--target-processes") != null) and
  (.profile_data.report_kinds | index("ncu_report") != null)
' "${NCU_RESULT_JSON}" >/dev/null

TIMING_TMP="${TMP_DIR}/timing"
mkdir -p "${TIMING_TMP}/results"
printf '100\n' > "${TIMING_TMP}/results/build_start"
printf '115\n' > "${TIMING_TMP}/results/build_end"
printf 'bad\n' > "${TIMING_TMP}/results/run_start"
printf '200\n' > "${TIMING_TMP}/results/run_end"
pushd "${TIMING_TMP}" >/dev/null
bash "${REPO_DIR}/scripts/collect_timing.sh" >/dev/null
popd >/dev/null
test -f "${TIMING_TMP}/results/pipeline_timing.json"
test ! -f "${TIMING_TMP}/results/timing.env"
jq -e '
  .build_time == 15 and
  .queue_time == 0 and
  .run_time == 0
' "${TIMING_TMP}/results/pipeline_timing.json" >/dev/null

echo "result profile_data test passed"
