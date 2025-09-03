#!/bin/bash
set -e
system="$1"
mkdir -p artifacts

# コードを取得して、必要であればtar -xcvf などして、コードのルートにcdする
git clone https://github.com/RIKEN-LQCD/qws.git
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
	make -j 2 fugaku_benchmark= omp=1  compiler=gnu arch=skylake rdma= mpi= powerapi=
	#gcc -v
	;;
    RC_GH200)
	echo "touch main (THIS IS a dummy executable to check CI jobs)"
	touch main ############################# THIS IS a dummy executable to check CI jobs
	;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
cp main ../artifacts
