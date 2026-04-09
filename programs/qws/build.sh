#!/bin/bash
set -e
system="$1"
mkdir -p artifacts

# bk_fetch_source でソースコード取得とメタデータ収集
source scripts/bk_functions.sh
bk_fetch_source https://github.com/RIKEN-LQCD/qws.git qws

cd qws

# システムに合わせてbuild方法を書く。systemの選択肢はlist.csvに合わせる。
case "$system" in
    Fugaku)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_cross rdma= mpi=1 powerapi=
	;;
    FugakuCN)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_native rdma= mpi=1 powerapi=
	;;
    FugakuLN)
	# Private repository access check (CI connectivity test)
	git clone --depth 1 --filter=blob:none --sparse https://${GHYN}@github.com/RIKEN-RCCS/FS_Benchmarks.git
	ls FS_Benchmarks
	cd FS_Benchmarks
	git sparse-checkout set QWS
	ls QWS
	cd ..
	# QWS build (dummy for LN)
	make -j 2 fugaku_benchmark= omp=1  compiler=gnu arch=skylake rdma= mpi= powerapi=
	#gcc -v
	;;
    FNCX)
	# Dummy build for Docker runner testing (no compiler needed)
	echo "Dummy build for FNCX Docker runner test"
	echo aaaa > main
	;;
    RC_GH200)
	module load system/qc-gh200 nvhpc-hpcx/25.9
	### QWSはNeoverse版やGPU版はないので汎用版としてとりあえずarch=skylakeを指定している
 	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
	;;
    RC_GENOA)
	module load system/genoa  mpi/openmpi-x86_64
 	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
    ;;
	RC_DGXSP)
	source /etc/profile.d/modules.sh
	module system/ng-dgx nvhpc-hpcx/26.3
	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
	;;
	RC_FX700)
	module system/fx700 FJSVstclanga
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_native rdma= mpi=1 powerapi=
	;;
    MiyabiG)
	### QWSはNeoverse版やGPU版はないので汎用版としてとりあえずarch=skylakeを指定している
 	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
        ;;
    MiyabiC)
 	make -j 8 fugaku_benchmark= omp=1  compiler=intel arch=skylake rdma= mpi=1 powerapi=
        ;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
cp main ../artifacts
