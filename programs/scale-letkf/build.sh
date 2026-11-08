#!/bin/bash
set -e
system="$1"
TOPDIR=`pwd`
mkdir -p artifacts

REPO_URL="https://github.com/SCALE-LETKF-RIKEN/scale-letkf-FugakuNEXT"
REPO_DIR="scale-letkf-FugakuNEXT"
BRANCH="${SCALE_LETKF_BRANCH:-master}"
SOURCE_COMMIT="${SCALE_LETKF_SOURCE_COMMIT:-}"

source scripts/bk_build.sh

if [[ "$system" == RIKYU ]]; then
  set -euo pipefail
  module load "${SCALE_LETKF_MODULE:-nvhpc-hpcx/26.3}"
  nc="${SCALE_LETKF_NC_CONFIG:-nc-config}"
  nf="${SCALE_LETKF_NF_CONFIG:-nf-config}"
  command -v "$nc" >/dev/null && command -v "$nf" >/dev/null || exit 1
  export SCALE_SYS=Linux64-nvidia SCALE_ENABLE_OPENMP=F SCALE_ENABLE_OPENACC=T
  export SCALE_ENABLE_MATHLIB=T
  SCALE_NETCDF_INCLUDE="$("$nc" --cflags) $("$nf" --fflags)"
  SCALE_NETCDF_LIBS="$("$nf" --flibs) $("$nc" --libs)"
  SCALE_MATHLIB_LIBS="${SCALE_LETKF_MATHLIB_LIBS:--L$(dirname "$(command -v nvfortran)")/../lib -llapack -lblas}"
  export SCALE_NETCDF_INCLUDE SCALE_NETCDF_LIBS SCALE_MATHLIB_LIBS
  LD_LIBRARY_PATH="$("$nf" --prefix)/lib:$("$nc" --prefix)/lib:${LD_LIBRARY_PATH:-}"
  export LD_LIBRARY_PATH
  jobs="${SCALE_LETKF_BUILD_JOBS:-4}"
  [[ "$jobs" =~ ^[1-9][0-9]?$ ]] || exit 2
  bk_build_source "$REPO_URL" "$BRANCH" "$SOURCE_COMMIT"
  cd "$BK_SOURCE_DIR"
  # NVIDIA HPC SDK bug 6861191: compile mod_mkinit at O1.
  bk_source_adjustment nvhpc-mkinit-o1 'Compile mod_mkinit at O1 for NVIDIA HPC SDK bug 6861191' \
      scale/scale-rm/src/Makefile bash -c '
          file=scale/scale-rm/src/Makefile
          if ! grep -q "# NVIDIA HPC SDK Bug 6861191 workaround" "$file"; then
              cat >> "$file" <<"MAKEFILE"

# NVIDIA HPC SDK Bug 6861191 workaround
MKINIT_FFLAGS := $(filter-out -fast -O% -Mvect%,$(FFLAGS)) -O1
$(BUILD_DIR)/mod_mkinit.o: FFLAGS = $(MKINIT_FFLAGS)
MAKEFILE
          fi
      '
  acc_flags='-acc -cuda -Minfo=accel -cudalib=cusparse,nvtx -DUSE_CUDALIB -gpu=cc100'
  make -C scale/scale-rm/src -j "$jobs" "FFLAGS_OPENACC=$acc_flags"
  make -C scale/scale-letkf/scale -j "$jobs" "FFLAGS_OPENACC=$acc_flags"
  bk_publish_source_runtime \
      scale/scale-letkf/scale/ensmodel/scale-rm_pp_ens \
      scale/scale-letkf/scale/ensmodel/scale-rm_init_ens \
      scale/scale-letkf/scale/ensmodel/scale-rm_ens \
      scale/scale-letkf/scale/letkf/letkf

  exit 0
fi

bk_fetch_source "${REPO_URL}" "${REPO_DIR}" "${BRANCH}" "${SOURCE_COMMIT}"
cd "${REPO_DIR}"

case "$system" in
  Fugaku)
    source setup-env.Fugaku.sh
    cd scale/scale-rm/src
    make -j
    cd ../../scale-letkf/scale
    make
    cd $TOPDIR
  ;;
  RC_GH200)
    source setup-env.RC_GH200.sh
    cd scale/scale-rm/src
    make -j
    cd ../../scale-letkf/scale
    make
    cd $TOPDIR
  ;;
  *)
    echo "Unknown system: $system"
    exit 1
  ;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
mkdir -p artifacts/bin
mkdir -p artifacts/test

# Copy only necessary executables
cp scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_pp_ens artifacts/bin/
cp scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_init_ens artifacts/bin/
cp scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_ens artifacts/bin/
cp scale-letkf-FugakuNEXT/scale/scale-letkf/scale/letkf/letkf artifacts/bin/

# Copy test directories (configuration files only)
cp -r scale-letkf-FugakuNEXT/test/benchmark.Fugaku_128x128 artifacts/test/
cp -r scale-letkf-FugakuNEXT/test/benchmark.Fugaku_1280x1280 artifacts/test/
cp -r scale-letkf-FugakuNEXT/test/benchmark.RC_GH200_128x128 artifacts/test/

# Copy setup environment script for RC_GH200
cp scale-letkf-FugakuNEXT/setup-env.RC_GH200.sh artifacts/
