#!/bin/bash
set -euo pipefail

system="$1"

CPU_ARCHIVE="/vol0003/rccs-sdt/data/a01008/apps/ffb/ffb-frt_cpu.fugaku.tar.gz"
GPU_ARCHIVE="/lvs0/rccs-sdt/kazuto.ando/apps/ffb/ffb-acc_gpu.gh.tar.gz"
WORK_DIR="ffb_src"

mkdir -p artifacts
rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

case "$system" in
  FugakuCN)
    archive="${CPU_ARCHIVE}"
    exe_relpath="bin/les3x.mpi"
    ;;
  RC_GH200)
    archive="${GPU_ARCHIVE}"
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

tar -xzf "$archive" -C "${WORK_DIR}" --strip-components=1
cd "${WORK_DIR}"

chmod +x make.FP3.sh
bash ./make.FP3.sh

if [[ ! -f "$exe_relpath" ]]; then
  echo "Built executable not found: ${exe_relpath}" >&2
  exit 1
fi

cp "$exe_relpath" "../artifacts/les3x.mpi"
