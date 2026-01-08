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
mv scale-letkf-FugakuNEXT artifacts
