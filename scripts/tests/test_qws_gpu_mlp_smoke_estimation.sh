#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/programs" "${TMP_DIR}/scripts" "${TMP_DIR}/results" "${TMP_DIR}/qws"
cp -R "${REPO_DIR}/programs/qws" "${TMP_DIR}/programs/qws"
cp "${REPO_DIR}/scripts/bk_functions.sh" "${TMP_DIR}/scripts/bk_functions.sh"
cp -R "${REPO_DIR}/scripts/estimation" "${TMP_DIR}/scripts/estimation"
cp -R "${REPO_DIR}/scripts/result_server" "${TMP_DIR}/scripts/result_server"

pushd "${TMP_DIR}" >/dev/null
set -- results/result0.json
export BK_QWS_GPU_MLP_SMOKE=true
export BK_QWS_GPU_MLP_SMOKE_MODE=prediction
source programs/qws/estimate.sh

pushd qws >/dev/null
qws_emit_estimation_data_from_fom 10 > ../results/result
popd >/dev/null

grep -q '^SECTION:gpu_kernel_region ' results/result
test -f results/estimation_artifacts/qws_gpu_kernel_mlp_v15_pred.csv
grep -q 'qws_smoke_kernel_0' results/estimation_artifacts/qws_gpu_kernel_mlp_v15_pred.csv

rm -rf results
mkdir -p results qws
export BK_QWS_GPU_MLP_SMOKE_MODE=perftools
pushd qws >/dev/null
qws_emit_estimation_data_from_fom 10 > ../results/result
popd >/dev/null

grep -q '^SECTION:gpu_kernel_region ' results/result
test -f results/estimation_artifacts/qws_gpu_kernel_mlp_v15_input.csv
grep -q 'qws_smoke_uses_perftools_example' results/estimation_artifacts/qws_gpu_kernel_mlp_v15_input.csv
popd >/dev/null

echo "qws gpu mlp smoke estimation test passed"
