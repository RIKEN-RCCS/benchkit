#!/bin/bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/scripts"
cp -R "$REPO_DIR/scripts/estimation" "$TMP_DIR/scripts/"
cp -R "$REPO_DIR/scripts/common" "$TMP_DIR/scripts/"
cp -R "$REPO_DIR/scripts/result_server" "$TMP_DIR/scripts/"
cd "$TMP_DIR"
source scripts/estimation/section_packages/gpu_kernel_lightgbm_v11.sh
export BK_GPU_LIGHTGBM_PYTHON="${BK_TEST_ESTIMATION_PYTHON:-python3.12}"
export BK_GPU_LIGHTGBM_FETCH_PERFTOOLS=0
export BK_GPU_LIGHTGBM_PREDICTION_CSV="$TMP_DIR/pred.csv"
export BK_GPU_LIGHTGBM_INPUT_CSV="$TMP_DIR/input.csv"
cat > input.csv <<'EOF'
Kernel Name,Duration [ns]
same,900
same,100
same,300
EOF
cat > pred.csv <<'EOF'
meta-kernel,meta-src_gpu,meta-tgt_gpu,O-Execution Time,benchkit-source-time-ns,benchkit-grid-size,benchkit-block-size
same,GB200,H100,400,200,10,128
same,GB200,H100,2700,900,20,256
EOF
item='{"name":"gpu","time":11,"kernel_name":"same"}'
result=$(bk_section_package_transform_gpu_kernel_lightgbm_v11 "$item" 1 1 1 section)
jq -e '.estimation_package == "gpu_kernel_lightgbm_v11" and .model.version == "1.1" and
  .scaling_method == "gpu-kernel-lightgbm-v1.1" and (.time - 31 | fabs) < 0.000001 and
  [.metrics.matched_kernels[].source_time_ns] == [200,900] and
  [.metrics.matched_kernels[].configuration.block_size] == [128,256]' <<< "$result" >/dev/null
# Discover the opt-in package through the ordinary section dispatcher.
source scripts/estimation/common.sh
source scripts/estimation/packages/instrumented_app_sections_dummy.sh
breakdown=$(jq -cn --argjson item "$item" '{sections:[$item + {estimation_package:"gpu_kernel_lightgbm_v11"}]}')
transformed=$(bk_top_level_transform_breakdown "$breakdown" 1 1 1 identity identity)
jq -e '.sections[0].estimation_package == "gpu_kernel_lightgbm_v11" and
  .sections[0].time == 31 and .sections[0].metrics.source_time_column == "benchkit-source-time-ns"' <<< "$transformed" >/dev/null
# Dynamic version selection must not change subsequent v1.0 calls.
[[ "$(_bk_gpu_lightgbm_model_dir /example)" == /example/LightGBM_model/1.0 ]]
cat > pred.csv <<'EOF'
meta-kernel,meta-src_gpu,meta-tgt_gpu,O-Execution Time
same,GB200,H100,400
EOF
if bk_section_package_transform_gpu_kernel_lightgbm_v11 "$item" 1 1 1 section >/dev/null 2>&1; then
  echo 'Unaligned prediction was unexpectedly accepted' >&2
  exit 1
fi
echo 'LightGBM v1.1 aligned prediction tests passed'
