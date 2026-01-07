#!/bin/bash
set -e
system="$1"

echo "[LQCD_dw_solver] Building on system: $system"
mkdir -p artifacts
#git clone https://github.com/RIKEN-LQCD/qws.git

TARDIR=./
case "$system" in
  Fugaku*)
    TARDIR=/vol0004/share/ra000001/kanamori/benchkit
    ;;
  Miyabi*)
    TARDIR=/home/q49000/benchkit_appsrc
    ;;
  *)
    ;;
esac
echo "soruce location " $TARDIR

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
      cp $BIN ../artifacts
      ;;
    MiyabiG) 
      # OpenACC
      cp Makefile_openacc Makefile
      make -j 8 lib
      cd benchmark/domainwall/
      make -j 8
      cd -
      mv $BIN $BIN_openacc
      cp $BIN_openacc ../artifacts
      # CUDA
      rm -r build
      cp Makefile_cuda Makefile
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
