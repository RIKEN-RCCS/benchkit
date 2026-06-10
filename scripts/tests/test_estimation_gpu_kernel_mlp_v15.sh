#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT
PREDICTION_FIXTURE="${REPO_DIR}/programs/qws/fixtures/gpu_kernel_mlp_v15_pred.csv"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping gpu_kernel_mlp_v15 estimation test"
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; skipping gpu_kernel_mlp_v15 estimation test"
  exit 0
fi
if [[ ! -f "$PREDICTION_FIXTURE" ]]; then
  echo "prediction fixture not found: $PREDICTION_FIXTURE" >&2
  exit 1
fi

cat > "${TMP_DIR}/breakdown.json" <<EOF
{
  "sections": [
    {
      "name": "gpu_kernel_region",
      "bench_time": 0.009,
      "estimation_package": "gpu_kernel_mlp_v15",
      "artifacts": [
        {"path": "${PREDICTION_FIXTURE}"}
      ]
    },
    {
      "name": "cpu_tail",
      "bench_time": 0.001,
      "estimation_package": "identity"
    }
  ],
  "overlaps": []
}
EOF

pushd "${REPO_DIR}" >/dev/null
source scripts/estimation/common.sh
source scripts/estimation/packages/instrumented_app_sections_dummy.sh

export BK_GPU_MLP_ARTIFACT_MODE="prediction"
export BK_GPU_MLP_PYTHON="python3"

transformed=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")
popd >/dev/null

echo "$transformed" | jq -e '
  (.sections | length == 2) and
  .sections[0].name == "gpu_kernel_region" and
  .sections[0].time == 0.006 and
  .sections[0].bench_time == 0.009 and
  .sections[0].scaling_method == "gpu-kernel-mlp-v1.5" and
  .sections[0].estimation_package == "gpu_kernel_mlp_v15" and
  .sections[0].package_applicability.status == "applicable" and
  .sections[0].metrics.kernel_count == 3 and
  .sections[0].metrics.kernels[0].metrics."Memory Throughput [%]" == 48 and
  .sections[1].time == 0.001
' >/dev/null

FAKE_PERFTOOLS="${TMP_DIR}/PerfTools"
mkdir -p "${FAKE_PERFTOOLS}/MLP_NN/v1.5"
cat > "${FAKE_PERFTOOLS}/MLP_NN/v1.5/predict_v15.py" <<'PY'
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--csv", required=True)
parser.add_argument("--row", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--log")
args = parser.parse_args()

if args.row != "all":
    raise SystemExit(f"unexpected row selector: {args.row}")
with open(args.csv, encoding="utf-8") as handle:
    if "probe_kernel" not in handle.read():
        raise SystemExit("input CSV was not passed to fake predictor")

with open(args.out, "w", encoding="utf-8") as handle:
    handle.write("kernel_name,src_gpu,tgt_gpu,Execution Time [ns],Memory Throughput [%]\n")
    handle.write("probe_kernel,A100,H100,4000000,51\n")

if args.log:
    with open(args.log, "w", encoding="utf-8") as handle:
        handle.write("fake predictor called\n")
PY

cat > "${TMP_DIR}/input.csv" <<'EOF'
kernel_name,src_gpu,tgt_gpu
probe_kernel,A100,H100
EOF

cat > "${TMP_DIR}/breakdown_input.json" <<EOF
{
  "sections": [
    {
      "name": "gpu_kernel_region",
      "bench_time": 0.011,
      "estimation_package": "gpu_kernel_mlp_v15",
      "artifacts": [
        {"path": "${TMP_DIR}/input.csv"}
      ]
    }
  ],
  "overlaps": []
}
EOF

pushd "${REPO_DIR}" >/dev/null
export BK_GPU_MLP_ARTIFACT_MODE="input"
export BK_GPU_MLP_PERFTOOLS_ROOT="${FAKE_PERFTOOLS}"
export BK_GPU_MLP_OUTPUT_DIR="${TMP_DIR}/mlp_outputs"

transformed_from_input=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown_input.json")" "1" "1" "1" "identity" "identity")
popd >/dev/null

echo "$transformed_from_input" | jq -e '
  (.sections | length == 1) and
  .sections[0].name == "gpu_kernel_region" and
  .sections[0].time == 0.004 and
  .sections[0].bench_time == 0.011 and
  .sections[0].scaling_method == "gpu-kernel-mlp-v1.5" and
  .sections[0].metrics.kernel_count == 1 and
  .sections[0].metrics.kernels[0].name == "probe_kernel" and
  .sections[0].artifacts[-1].kind == "gpu_mlp_prediction_csv"
' >/dev/null

test -f "${TMP_DIR}/mlp_outputs/unknown_gpu_kernel_region_local_pred.csv"
test -f "${TMP_DIR}/mlp_outputs/unknown_gpu_kernel_region_local.log"

echo "gpu_kernel_mlp_v15 section estimation test passed"
