#!/bin/bash
set -e
system="$1"

echo "[LQCD_dw_solver] Building on system: $system"
mkdir -p artifacts

REPO_URL="${LQCD_DW_SOLVER_REPO_URL:-https://github.com/i-kanamori/LQCD-DWF-solver.git}"
REPO_DIR="LQCD_dw_solver"
BRANCH="${LQCD_DW_SOLVER_BRANCH:-main}"
SOURCE_COMMIT="${LQCD_DW_SOLVER_SOURCE_COMMIT:-}"

# bk_fetch_source でソースコード取得とメタデータ収集
source scripts/bk_build.sh
# 旧方式（tarball 展開 + シンボリックリンク）の作業ディレクトリが残っていると
# bk_fetch_source が clone を省略して古いソースを使ってしまうため、
# git checkout でないものは取り除いてから取得する
if [ -L "${REPO_DIR}" ] || { [ -e "${REPO_DIR}" ] && [ ! -d "${REPO_DIR}/.git" ]; }; then
  echo "[LQCD_dw_solver] Removing stale non-git source directory: ${REPO_DIR}"
  rm -rf "${REPO_DIR}"
fi
bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "${BRANCH}" "${SOURCE_COMMIT}"

cd "${REPO_DIR}"

# 上流ソース（d5a823d 時点）の不具合回避:
# init_alt_Accel.cpp が存在しない DeviceManager_CUDA::init_prempi() を呼んでおり、
# CUDA 版（Makefile_cuda）がコンパイルできない。init_alt_Accel_prempi() は
# use_mpi = gpu_aware のときだけ呼ばれ、CUDA 版は use_mpi = yes なので、
# この呼び出しを削除しても動作は変わらない。上流で修正されたら不要。
apply_cuda_init_prempi_workaround () {
  local f=src/lib_alt_Accel/init_alt_Accel.cpp
  if grep -q "DeviceManager_CUDA::init_prempi" "$f" && \
     ! grep -q "init_prempi" src/lib_alt_Accel/ResourceManager/deviceManager_CUDA.h; then
    sed -i -e '/DeviceManager_CUDA::init_prempi/d' "$f"
    echo "[LQCD_dw_solver] Applied workaround: removed DeviceManager_CUDA::init_prempi call"
  fi
}
apply_cuda_init_prempi_workaround

# GPU 版の Makefile は use_device_arch = auto（nvidia-smi で検出）が既定。
# GPU の見えないログインノードでビルドすると失敗するため、明示的に指定する。
set_device_arch () {
  sed -i -e "s/^use_device_arch *= *.*/use_device_arch = $1/" Makefile
  grep -q "^use_device_arch = $1\$" Makefile
}

BIN=benchmark/domainwall/bridge.elf
BIN_openacc=benchmark/domainwall/bridge_openacc.elf
BIN_cuda=benchmark/domainwall/bridge_cuda.elf

case "$system" in
    Fugaku)
      # fugaku coross comipler
      cp Makefile_fugaku_acle Makefile
      if [ ! -e Makefile_target.inc.keep ]; then
        cp Makefile_target.inc Makefile_target.inc.keep
      fi
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      cp $BIN ../artifacts
      #fccpx --version
      ;;
    FugakuCN)
      # fugaku native comipler
      cp Makefile_fugaku_acle Makefile
      if [ ! -e Makefile_target.inc.keep ]; then
        cp Makefile_target.inc Makefile_target.inc.keep
        sed -i "s/FCCpx/FCC/g" Makefile_target.inc
      fi
      make -j 12 lib
      cd benchmark/domainwall/
      make -j 12
      cd -
      cp $BIN ../artifacts
      ;;
    MiyabiC|AVX512)
      cp Makefile_simd_avx512 Makefile
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      cp $BIN ../artifacts
      ;;
    MiyabiG)
      # OpenACC
      cp Makefile_openacc Makefile
      set_device_arch hopper
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      mv $BIN $BIN_openacc
      cp $BIN_openacc ../artifacts
      # CUDA
      rm -r build
      cp Makefile_cuda Makefile
      set_device_arch hopper
      make clean
      make -j 8 lib
      cd benchmark/domainwall/
      make clean
      make -j 8
      cd -
      mv $BIN $BIN_cuda
      cp $BIN_cuda ../artifacts
      ;;
    RIKYU)
      # NVIDIA Grace + B200 (sm_100)。cross 構成でビルドはログインノード
      module load nvhpc-hpcx/26.3
      # OpenACC
      cp Makefile_openacc Makefile
      set_device_arch blackwell
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      mv $BIN $BIN_openacc
      cp $BIN_openacc ../artifacts
      # CUDA
      rm -rf build
      cp Makefile_cuda Makefile
      set_device_arch blackwell
      make clean
      make -j 8 lib
      cd benchmark/domainwall/
      make clean
      make -j 8
      cd -
      mv $BIN $BIN_cuda
      cp $BIN_cuda ../artifacts
      ;;
    OpenACC)
      cp Makefile_openacc Makefile
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      cp $BIN ../artifacts
      ;;
    CUDA)
      cp Makefile_cuda Makefile
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      cp $BIN ../artifacts
      ;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
#cp $BIN ../artifacts # moved to each section
