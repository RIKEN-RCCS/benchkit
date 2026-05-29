#!/bin/bash
set -e
system="$1"
mkdir -p artifacts

# bk_fetch_source でソースコード取得とメタデータ収集
source scripts/bk_functions.sh
bk_fetch_source https://github.com/RIKEN-LQCD/qws.git qws

cd qws

qws_profiler_tool="fapp"

# システムに合わせてbuild方法を書く。systemの選択肢はlist.csvに合わせる。
case "$system" in
    Fugaku)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_cross rdma= mpi=1 powerapi= profiler=${qws_profiler_tool}
	;;
    FugakuCN)
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_native rdma= mpi=1 powerapi= profiler=${qws_profiler_tool}
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
    AI4SS)
	module load nvhpc-hpcx/26.3
	make -j 8 omp=1 compiler=nvhpc-hpcx arch=grace rdma= mpi=1
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
	module load system/ng-dgx nvhpc-hpcx/26.3
	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
	;;
	RC_FX700)
	module load system/fx700 FJSVstclanga
	make -j 8 fugaku_benchmark= omp=1  compiler=fujitsu_native rdma= mpi=1 powerapi= SYSLIBS=
	;;
    MiyabiG)
	### QWSはNeoverse版やGPU版はないので汎用版としてとりあえずarch=skylakeを指定している
 	make -j 8 fugaku_benchmark= omp=1  compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=
        ;;
    MiyabiC)
 	make -j 8 fugaku_benchmark= omp=1  compiler=intel arch=skylake rdma= mpi=1 powerapi=
        ;;
    GenkaiA|GenkaiB|GenkaiC)
	module load intel/2023.2 mvapich/3.0-intel2023.2
	make -j 8 fugaku_benchmark= omp=1 compiler=intel arch=skylake rdma= mpi=1 powerapi= CC=mpicc CXX=mpicxx
	;;
    Grand_C|Grand_G)
	module load intel impi
	make -j 8 fugaku_benchmark= omp=1 compiler=intel arch=skylake rdma= mpi=1 powerapi=
	;;
    AOBA_A|AOBA_S)
	make -j 8 fugaku_benchmark= omp=1 compiler=nec arch=sx rdma= mpi=1 powerapi=
	;;
    AOBA_B)
	make -j 8 fugaku_benchmark= omp=1 compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi= CC=mpicc CXX=mpic++
	;;
    Odyssey)
	module load odyssey
	make compiler=fujitsu_cross arch=postk -j 8
	;;
    Aquarius)
	module purge
	module load intel
	source /work/opt/local/x86_64/cores/intel/2023.0.0/mpi/latest/env/vars.sh
	make compiler=intel arch=skylake rdma= -j8
	;;
    Pegasus)
	module load intel/2025.3.1 intmpi/2025.3.1
	make compiler=intel arch=skylake mpi=1 omp=1 rdma=
	;;
    Sirius)
	module load aocc/5.0.0 openmpi/5.0.10/aocc5.0.0
	make -j4 compiler=aocc arch=zen4 rdma= mpi=1 omp=1 profiler=timing \
	    AMD_MARCH=-march=znver4 cppflags="-DARCH_AVX512" main
	;;
    TSUBAME4)
	module load openmpi/5.0.10-gcc aocc/4.1.0
	export OMPI_CC=clang OMPI_CXX=clang++ OMPI_FC=flang
	make -j4 compiler=aocc arch=zen4 rdma= mpi=1 omp=1 profiler=timing \
	    AMD_MARCH=-march=znver4 cppflags="-DARCH_AVX512" main
	;;
    Camphor3)
	camphor3_modulepath="${MODULEPATH:-}"
	if [[ -r /etc/profile.d/modules.sh ]]; then
	    source /etc/profile.d/modules.sh
	elif [[ -r /etc/profile.d/z00_lmod.sh ]]; then
	    source /etc/profile.d/z00_lmod.sh
	else
	    echo "qws: no module init script found" >&2
	fi
	if [[ -n "${MODULEPATH:-}" ]]; then
	    camphor3_modulepath="${MODULEPATH}"
	fi
	module purge
	if [[ -n "${camphor3_modulepath:-}" ]]; then
	    export MODULEPATH="${camphor3_modulepath}"
	fi
	module load slurm/2022 SysA/2022 intel/2023.2 intelmpi/2023.2 PrgEnvIntel/2023
	make -j 8 fugaku_benchmark= omp=1 compiler=intel arch=skylake rdma= mpi=1 powerapi=
	;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
cp main ../artifacts
