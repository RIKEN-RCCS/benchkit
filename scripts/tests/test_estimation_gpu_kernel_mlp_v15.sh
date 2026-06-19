#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT
PREDICTION_FIXTURE="${REPO_DIR}/scripts/tests/fixtures/gpu_kernel_mlp_v15_pred.csv"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping gpu_kernel_mlp_v15 estimation test"
  exit 0
fi

PYTHON_BIN="${BK_TEST_ESTIMATION_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN=$(command -v "$candidate")
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.11+ not found; skipping gpu_kernel_mlp_v15 estimation test"
  exit 0
fi
if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  echo "Python 3.11+ not found; skipping gpu_kernel_mlp_v15 estimation test"
  exit 0
fi
if [[ ! -f "$PREDICTION_FIXTURE" ]]; then
  echo "prediction fixture not found: $PREDICTION_FIXTURE" >&2
  exit 1
fi

cat > "${TMP_DIR}/mlp_input.csv" <<'EOF'
kernel_name,Execution Time
qws_smoke_kernel_0,1500000
qws_smoke_kernel_1,2500000
qws_smoke_kernel_2,2000000
EOF

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
export BK_GPU_MLP_INPUT_CSV="${TMP_DIR}/mlp_input.csv"
export BK_GPU_MLP_PYTHON="$PYTHON_BIN"

transformed=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown.json")" "1" "1" "1" "identity" "identity")
popd >/dev/null
unset BK_GPU_MLP_INPUT_CSV

echo "$transformed" | jq -e '
  (.sections | length == 2) and
  .sections[0].name == "gpu_kernel_region" and
  .sections[0].time == 0.009 and
  .sections[0].bench_time == 0.009 and
  .sections[0].scaling_method == "identity" and
  .sections[0].estimation_package == "identity" and
  .sections[0].requested_estimation_package == "gpu_kernel_mlp_v15" and
  .sections[0].fallback_used == "identity" and
  .sections[0].package_applicability.status == "fallback" and
  (.sections[0].package_applicability.missing_inputs | index("gpu_kernel_section_kernel_selector_required")) and
  .sections[0].metrics.kernel_count == 3 and
  .sections[0].metrics.unique_kernel_count == 3 and
  .sections[0].metrics.source_time_column == "Execution Time" and
  .sections[0].metrics.total_source_time_ns == 6000000 and
  .sections[0].metrics.total_predicted_time_ns == 6000000 and
  .sections[0].metrics.sample_predicted_time == 0.006 and
  .sections[0].metrics.app_gpu_section_time == 0.009 and
  .sections[0].metrics.section_time_ratio_predicted_over_source == 1 and
  .sections[0].metrics.time_ratio_predicted_over_source == 1 and
  .sections[0].metrics.speedup_factor_source_over_predicted == 1 and
  .sections[0].metrics.kernels[0].source_time_ns == 1500000 and
  .sections[0].metrics.kernels[0].time_ratio_predicted_over_source == 1 and
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

for version_script in \
  "v2.1 predict_v21.py" \
  "v4.0 predict_v40.py" \
  "v4.1 predict_v41.py"; do
  read -r version_dir script_name <<< "$version_script"
  mkdir -p "${FAKE_PERFTOOLS}/MLP_NN/${version_dir}"
  cp "${FAKE_PERFTOOLS}/MLP_NN/v1.5/predict_v15.py" \
    "${FAKE_PERFTOOLS}/MLP_NN/${version_dir}/${script_name}"
done

cat > "${TMP_DIR}/input.csv" <<'EOF'
kernel_name,src_gpu,tgt_gpu,Execution Time
probe_kernel,A100,H100,2000000
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
  .sections[0].time == 0.022 and
  .sections[0].bench_time == 0.011 and
  .sections[0].scaling_method == "gpu-kernel-mlp-v1.5" and
  .sections[0].estimation_package == "gpu_kernel_mlp_v15" and
  .sections[0].package_applicability.status == "applicable" and
  .sections[0].metrics.kernel_count == 1 and
  .sections[0].metrics.unique_kernel_count == 1 and
  .sections[0].metrics.kernel_names == ["probe_kernel"] and
  .sections[0].metrics.total_source_time_ns == 2000000 and
  .sections[0].metrics.total_predicted_time_ns == 4000000 and
  .sections[0].metrics.sample_predicted_time == 0.004 and
  .sections[0].metrics.app_gpu_section_time == 0.011 and
  .sections[0].metrics.section_time_ratio_predicted_over_source == 2 and
  .sections[0].metrics.time_ratio_predicted_over_source == 2 and
  .sections[0].metrics.speedup_factor_source_over_predicted == 0.5 and
  .sections[0].metrics.kernels[0].name == "probe_kernel" and
  .sections[0].metrics.kernels[0].source_time_ns == 2000000 and
  .sections[0].metrics.kernels[0].time_ratio_predicted_over_source == 2 and
  (.sections[0].artifacts | map(.kind) | index("gpu_mlp_prediction_csv") != null) and
  (.sections[0].artifacts | map(.kind) | index("gpu_mlp_input_csv") != null) and
  (.sections[0].artifacts | map(.kind) | index("gpu_mlp_log") != null)
' >/dev/null

test -f "${TMP_DIR}/mlp_outputs/unknown_gpu_kernel_region_local_pred.csv"
test -f "${TMP_DIR}/mlp_outputs/unknown_gpu_kernel_region_local.log"

unset BK_GPU_MLP_OUTPUT_DIR
for package_version in \
  "gpu_kernel_mlp_v21 v2.1" \
  "gpu_kernel_mlp_v40 v4.0" \
  "gpu_kernel_mlp_v41 v4.1"; do
  read -r package_name version_label <<< "$package_version"
  cat > "${TMP_DIR}/breakdown_${package_name}.json" <<EOF
{
  "sections": [
    {
      "name": "gpu_kernel_region",
      "bench_time": 0.011,
      "estimation_package": "${package_name}",
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
  export BK_GPU_MLP_OUTPUT_DIR="${TMP_DIR}/${package_name}_outputs"
  transformed_family=$(bk_top_level_transform_breakdown "$(cat "${TMP_DIR}/breakdown_${package_name}.json")" "1" "1" "1" "identity" "identity")
  popd >/dev/null

  echo "$transformed_family" | jq -e \
    --arg package_name "$package_name" \
    --arg version_label "$version_label" '
    (.sections | length == 1) and
    .sections[0].name == "gpu_kernel_region" and
    .sections[0].time == 0.022 and
    .sections[0].bench_time == 0.011 and
    .sections[0].scaling_method == ("gpu-kernel-mlp-" + $version_label) and
    .sections[0].estimation_package == $package_name and
    .sections[0].model.name == ("PerfTools MLP_NN/" + $version_label) and
    .sections[0].model.version == $version_label and
    .sections[0].metrics.kernel_count == 1 and
    .sections[0].metrics.total_source_time_ns == 2000000 and
    .sections[0].metrics.total_predicted_time_ns == 4000000
  ' >/dev/null

  test -f "${TMP_DIR}/${package_name}_outputs/unknown_gpu_kernel_region_local_pred.csv"
  test -f "${TMP_DIR}/${package_name}_outputs/unknown_gpu_kernel_region_local.log"
done

echo "gpu_kernel_mlp_v15 section estimation test passed"
