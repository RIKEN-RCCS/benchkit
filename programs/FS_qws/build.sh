#!/bin/bash
set -e
system="$1"

echo "[FS_Benchmarks/QWS] Building on system: $system"
mkdir -p artifacts
git clone --depth 1  --filter=blob:none --sparse https://${GHYN}@github.com/RIKEN-RCCS/FS_Benchmarks.git
ls FS_Benchmarks
cd FS_Benchmarks
git sparse-checkout set QWS
ls QWS

case "$system" in
    Fugaku)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_cross rdma= mpi= powerapi=
	#fccpx --version
	;;
    FugakuCN)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_native rdma= mpi= powerapi=
	#fcc --version
	;;
    FugakuLN)
	#make -j 2 fugaku_benchmark= omp=1  compiler=gnu arch=skylake rdma= mpi= powerapi=
	echo "touch main (THIS IS a dummy executable to check CI jobs)"
	touch main ############################# THIS IS a dummy executable to check CI jobs
	#gcc -v
	;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
cp main ../artifacts
