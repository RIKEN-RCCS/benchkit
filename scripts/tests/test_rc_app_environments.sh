#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${REPO_DIR}"

active_rc_scripts=(
  programs/ffb/build.sh
  programs/ffb/run.sh
  programs/genesis/build.sh
  programs/genesis/run.sh
  programs/petsc-gmres/build.sh
  programs/petsc-gmres/run.sh
  programs/salmon/build.sh
  programs/salmon/run.sh
  programs/sbd/build.sh
  programs/sbd/run.sh
)

if rg -n '^[[:space:]]*module load system/' "${active_rc_scripts[@]}"; then
  echo "Active RC app routes must not load retired system modules" >&2
  exit 1
fi

for script in programs/ffb/build.sh programs/ffb/run.sh; do
  grep -Fq 'nvhpc-hpcx/25.7' "${script}"
done

grep -Fq 'export NVHPC_CUDA_HOME=' programs/ffb/build.sh
for script in \
  programs/genesis/build.sh programs/genesis/run.sh \
  programs/salmon/build.sh programs/salmon/run.sh \
  programs/sbd/build.sh programs/sbd/run.sh; do
  grep -Fq 'nvhpc-hpcx/26.9' "${script}"
done

for script in \
  programs/petsc-gmres/build.sh programs/petsc-gmres/run.sh \
  programs/salmon/build.sh programs/salmon/run.sh \
  programs/sbd/build.sh programs/sbd/run.sh; do
  grep -Fq 'nvhpc-hpcx/26.3' "${script}"
done

if rg -n 'system/genoa|mpi/openmpi-x86_64' programs/salmon/build.sh programs/salmon/run.sh; then
  echo "SALMON RC_GENOA must use the image-provided GNU/OpenMPI toolchain" >&2

grep -Fq 'LAPACK_VENDOR_FLAGS=-Wl,--no-as-needed' programs/salmon/build.sh
  exit 1

grep -Fq 'RC_DGXSP,yes,1,1,8,1:00:00' programs/sbd/list.csv
grep -Fq 'RC_GH200,yes,1,1,8,1:00:00' programs/sbd/list.csv
fi

echo "RC app environment test passed"
