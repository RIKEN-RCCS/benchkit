#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/programs" "${TMP_DIR}/scripts" "${TMP_DIR}/results"
cp -R "${REPO_DIR}/programs/genesis" "${TMP_DIR}/programs/genesis"
cp "${REPO_DIR}/scripts/bk_functions.sh" "${TMP_DIR}/scripts/bk_functions.sh"
cp -R "${REPO_DIR}/scripts/estimation" "${TMP_DIR}/scripts/estimation"
cp -R "${REPO_DIR}/scripts/result_server" "${TMP_DIR}/scripts/result_server"

pushd "${TMP_DIR}" >/dev/null
source programs/genesis/estimate.sh
test "${BK_ESTIMATION_BASELINE_EXP}" = "p8"

export BK_GENESIS_GPU_MLP_PROFILE=false
genesis_emit_estimation_data_from_fom 10 > results/no_profile.result
! grep -q '^SECTION:gpu_kernel_region ' results/no_profile.result

export BK_GENESIS_GPU_MLP_PROFILE=true
genesis_emit_estimation_data_from_fom 10 > results/no_archive.result 2> results/no_archive.err
! grep -q '^SECTION:gpu_kernel_region ' results/no_archive.result
grep -q 'profiler archive was not found' results/no_archive.err

touch results/padata0.tgz
genesis_emit_estimation_data_from_fom 10 > results/with_archive.result
grep -q '^SECTION:gpu_kernel_region time:10 estimation_package:gpu_kernel_lightgbm_v10 ' results/with_archive.result
grep -q 'artifact:results/padata0.tgz' results/with_archive.result

BK_GENESIS_GPU_SECTION_PACKAGE=gpu_kernel_mlp_v15 \
  bash -c 'source programs/genesis/estimate.sh; genesis_emit_estimation_data_from_fom 10' \
  > results/with_mlp_archive.result
grep -q '^SECTION:gpu_kernel_region time:10 estimation_package:gpu_kernel_mlp_v15 ' results/with_mlp_archive.result

BK_GENESIS_GPU_SECTION_PACKAGES=gpu_kernel_mlp_v15,gpu_kernel_lightgbm_v10 \
  bash -c 'source programs/genesis/estimate.sh; export BK_GENESIS_GPU_MLP_PROFILE=true; genesis_emit_estimation_data_from_fom 10' \
  > results/with_package_list.result
grep -q '^SECTION:gpu_kernel_region time:10 estimation_package:gpu_kernel_mlp_v15 ' results/with_package_list.result

cat > results/input_lightgbm.json <<'EOF'
{
  "code": "genesis",
  "Exp": "p8",
  "system": "MiyabiG",
  "FOM": 10,
  "node_count": 1,
  "fom_breakdown": {
    "sections": [
      {
        "name": "gpu_kernel_region",
        "time": 10,
        "estimation_package": "gpu_kernel_lightgbm_v10"
      },
      {
        "name": "other",
        "time": 1,
        "estimation_package": "identity"
      }
    ]
  }
}
EOF
bash -c 'source programs/genesis/estimate.sh; genesis_write_estimation_input_for_gpu_package results/input_lightgbm.json gpu_kernel_mlp_v15 results/input_mlp.json'
jq -e '
  .fom_breakdown.sections[0].estimation_package == "gpu_kernel_mlp_v15" and
  .fom_breakdown.sections[1].estimation_package == "identity"
' results/input_mlp.json >/dev/null

mkdir -p genesis_benchmark_input/npt/genesis2.0beta_3.5fs/apoa1
GENESIS_BENCHKIT_ROOT="$PWD" \
  bash -c 'source programs/genesis/estimate.sh; cd genesis_benchmark_input/npt/genesis2.0beta_3.5fs/apoa1; export BK_GENESIS_GPU_MLP_PROFILE=true; genesis_emit_estimation_data_from_fom 10' \
  > results/from_subdir.result
grep -q 'artifact:results/padata0.tgz' results/from_subdir.result
popd >/dev/null

echo "genesis gpu mlp estimation metadata test passed"
