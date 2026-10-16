#!/bin/bash
set -euo pipefail

system="$1"

CPU_ARCHIVE="/vol0003/rccs-sdt/data/a01008/apps/ffb/ffb-frt_cpu.fugaku.tar.gz"
GPU_ARCHIVE="/lvs0/rccs-sdt/kazuto.ando/apps/ffb/ffb-acc_gpu.gh.tar.gz"
WORK_DIR="ffb_src"

source scripts/bk_build.sh

mkdir -p artifacts
rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

case "$system" in
  FugakuCN)
    archive="${CPU_ARCHIVE}"
    archive_sha256="${FFB_CPU_ARCHIVE_SHA256:-${BK_FFB_CPU_ARCHIVE_SHA256:-}}"
    exe_relpath="bin/les3x.mpi"
    ;;
  RC_GH200)
    if ! type module >/dev/null 2>&1; then
      source /etc/profile.d/modules.sh
    fi
    module purge
    module load nvhpc-hpcx/25.7
    export NVHPC_CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
    nvhpc_sdk_root="$(dirname "$(dirname "${NVHPC_CUDA_HOME}")")"
    export NVCOMPILER_COMM_LIBS_HOME="${nvhpc_sdk_root}/comm_libs/$(basename "${NVHPC_CUDA_HOME}")"
    if [[ ! -d "${NVCOMPILER_COMM_LIBS_HOME}" ]]; then
      echo "NVHPC communication libraries not found: ${NVCOMPILER_COMM_LIBS_HOME}" >&2
      exit 1
    archive="${GPU_ARCHIVE}"
    archive_sha256="${FFB_GPU_ARCHIVE_SHA256:-${BK_FFB_GPU_ARCHIVE_SHA256:-}}"
    exe_relpath="bin.acc_gpu/les3x.mpi"
    ;;
  *)
    echo "Unknown system: $system" >&2
    exit 1
    ;;
esac

if [[ ! -f "$archive" ]]; then
  echo "Source archive not found: $archive" >&2
  exit 1
fi

bk_record_file_source_info "$archive" "$archive_sha256" "FFB source archive"
tar -xzf "$archive" -C "${WORK_DIR}" --strip-components=1
cd "${WORK_DIR}"

chmod +x make.FP3.sh
bash ./make.FP3.sh

if [[ ! -f "$exe_relpath" ]]; then
  echo "Built executable not found: ${exe_relpath}" >&2
  exit 1
fi

cp "$exe_relpath" "../artifacts/les3x.mpi"
