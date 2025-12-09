#!/bin/bash
set -e
system="$1"

echo "[LQCD_dw_solver] Building on system: $system"
mkdir -p artifacts
#git clone https://github.com/RIKEN-LQCD/qws.git

TARDIR=/vol0004/share/ra000001/kanamori/benchkit
TARBALL=LQCD_dw_solver_20251209_773762.tar.gz
SRC=`echo $TARBALL|sed -e "s/\.tar\.gz//"`
DIR=LQCD_dw_solver
if [ ! -d LQCD_dw_solver ]; then
  cp $TARDIR/$TARBALL .
  tar -zxf $TARBALL
  ln -s $SRC $DIR
fi

cd $DIR

BIN=benchmark/domainwall/bridge.elf

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
      ;;
    FugakuLN)
      echo "touch $BIN (THIS IS a dummy)"
      mkdir -p benchmark/domainwall/
      touch $BIN
      ;;
    MiyabiC|AVX512)
      cp Makefile_simd_avx512 Makefile
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      ;;
    MiyabiGOpenACC|OpenACC)
      cp Makefile_openacc Makefile
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      ;;
    MiyabiGCUDA|CUDA)
      cp Makefile_cuda Makefile
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      ;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
cp $BIN ../artifacts
