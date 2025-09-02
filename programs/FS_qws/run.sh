#!/bin/bash
set -e
system="$1"
nodes="$2"

echo "[FS_Benchmarks/QWS] Running on system: $system"
ls
if [ ! -d FS_Benchmarks ]; then
    git clone --depth 1  --filter=blob:none --sparse https://${GHYN}@github.com/RIKEN-RCCS/FS_Benchmarks.git
    ls FS_Benchmarks
    cd FS_Benchmarks
    git sparse-checkout set QWS
    cd ../
fi
cp artifacts/main FS_Benchmarks
cd FS_Benchmarks




case "$system" in
  Fugaku|FugakuCN)
    ./main 32 6 4 3   1 1 1 1    -1   -1  6 50 > CASE0
    ./check.sh CASE0 data/CASE0
    mkdir -p ../results
    echo FOM:dummy > ../results/result
    ;;
  FugakuLN)
    echo 'dummy call for CB test: QWS program: ./main 32 6 4 3   1 1 1 1    -1   -1  6 50'
    mkdir -p ../results
    #echo FOM:123.56 > ../results/result
    echo FOM:123.56 FOM_version:dummy Exp:ChechingPrivateRepo node_count:$nodes > ../results/result

    mkdir -p pa
    echo dummy > ./pa/padat.0
    echo dummy > ./pa/padat.1
    echo dummy > ./pa/padat.2
    echo dummy > ./pa/padat.3
    tar -czf ../results/padata0.tgz ./pa
    ls ../results/
    ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
    ;;
esac
