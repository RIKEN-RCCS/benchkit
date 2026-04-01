#!/bin/bash
set -e
system="$1"
mkdir -p artifacts

# コードを取得して、必要であればtar -xcvf などして、コードのルートにcdする
source scripts/bk_functions.sh
bk_fetch_source https://github.com/RIKEN-LQCD/qws.git qws
cd qws

# システムに合わせてbuild方法を書く。systemの選択肢はlist.csvに合わせる。
case "$system" in
    Fugaku)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_cross rdma= mpi=1 powerapi=
	#fccpx --version
	;;
    FugakuCN)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_native rdma= mpi=1 powerapi=
	#fcc --version
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
    RC_GH200)
	module load system/qc-gh200 nvhpc-hpcx/25.9
	### QWSはNeoverse版やGPU版はないので汎用版としてとりあえずarch=skylakeを指定している
 	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
	;;
    RC_GENOA)
	module load system/genoa  mpi/openmpi-x86_64
 	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
        ;;
    MiyabiG)
	### QWSはNeoverse版やGPU版はないので汎用版としてとりあえずarch=skylakeを指定している
 	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
        ;;
    MiyabiC)
 	make -j 8 fugaku_benchmark= omp=1  compiler=intel arch=skylake rdma= mpi=1 powerapi=
        ;;
    FNCX)
	echo "=== FNCX: bk_fetch_source smoke test ==="
	echo "gcc: $(which gcc 2>&1 || echo 'not found')"
	echo "make: $(which make 2>&1 || echo 'not found')"
	echo "git: $(which git 2>&1 || echo 'not found')"
	echo "md5sum: $(which md5sum 2>&1 || echo 'not found')"
	echo "Skipping actual build (no compiler expected)"
	echo "dummy" > ../artifacts/main
	;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
cp main ../artifacts
