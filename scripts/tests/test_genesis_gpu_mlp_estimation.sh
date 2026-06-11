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
grep -q '^SECTION:gpu_kernel_region ' results/with_archive.result
grep -q 'artifact:results/padata0.tgz' results/with_archive.result

mkdir -p genesis_benchmark_input/npt/genesis2.0beta_3.5fs/apoa1
GENESIS_BENCHKIT_ROOT="$PWD" \
  bash -c 'source programs/genesis/estimate.sh; cd genesis_benchmark_input/npt/genesis2.0beta_3.5fs/apoa1; export BK_GENESIS_GPU_MLP_PROFILE=true; genesis_emit_estimation_data_from_fom 10' \
  > results/from_subdir.result
grep -q 'artifact:results/padata0.tgz' results/from_subdir.result
popd >/dev/null

echo "genesis gpu mlp estimation metadata test passed"
