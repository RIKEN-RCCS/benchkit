#!/bin/bash
set -e
system="$1"
TOPDIR=`pwd`
mkdir -p artifacts

git clone https://github.com/SCALE-LETKF-RIKEN/scale-letkf-FugakuNEXT
cd scale-letkf-FugakuNEXT

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
