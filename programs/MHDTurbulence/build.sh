#!/bin/bash
# usage: bash programs/MHDTurbulence/build.sh system

set -e
system="$1"

code=MHDTurbulence
REPO=https://github.com/cfcanaoj/MHDTurbulence.git
BRANCH="${MHDTURBULENCE_BRANCH:-main}"
SOURCE_COMMIT="${MHDTURBULENCE_SOURCE_COMMIT:-}"
artdir=artifacts

echo "[${code}] Building on system: $system"

mkdir -p ${artdir}

source scripts/bk_functions.sh
bk_fetch_source "$REPO" "$code" "$BRANCH" "$SOURCE_COMMIT"

DIR=$code

cd $DIR
BIN=Simulation.x
case "$system" in
    MiyabiC)
	cd src_f90_omp_host
	echo "Compile cods in "`pwd`
	make
	echo "Executable is "${BIN}" and copied to "${artdir}
	cp ../exe/$BIN ../../${artdir}
	;;
    MiyabiG)
	cd src_f90_acc_device
	echo "Compile cods in "`pwd`
	make
	echo "Executable is "${BIN}" and copied to "${artdir}
	cp ../exe/$BIN ../../${artdir}
	;;
    RIKYU)
	module load nvhpc-hpcx-cuda13/26.5
	# Portability fixes; skipped when already upstream
	grep -q "integer,dimension(8) :: seed" src_f90_omp_host/main.f90 || \
	    patch -p1 < ../programs/${code}/patches/random_seed_put_size.patch
	grep -q "acc_init(acc_device_nvidia)" src_f90_acc_device/main.f90 || \
	    patch -p1 < ../programs/${code}/patches/acc_init_before_mpi.patch
	# ntiles is compile-time: one binary per list.csv rank count
	cd src_f90_acc_device
	for tiles in 1 4 8; do
	    make clean >/dev/null 2>&1 || true
	    sed -i "s/ntiles(3) = \[.*,.*,.*\]/ntiles(3) = [ ${tiles},1,1 ]/" config.f90
	    make > /dev/null
	    echo "Executable is "${BIN}".t"${tiles}" and copied to "${artdir}
	    cp ../exe/$BIN ../../${artdir}/${BIN}.t${tiles}
	done
	;;
# in the future, we may add this
#    MiyabiG/OpenMP)
#	cd src_f90_omp_device
#	echo "Compile cods in "`pwd`
#	make
#	echo "Executable is "${BIN}" and copied to "${artdir}
#	cp ../exe/$BIN ../../${artdir}
#	;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac

echo "Storing executables and related artifacts for subsequent CI/CD jobs."
