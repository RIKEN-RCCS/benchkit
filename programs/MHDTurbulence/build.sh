#!/bin/bash
# usage: bash programs/MHDTurbulence/build.sh system

set -e
system="$1"

code=MHDTurbulence
REPO=https://github.com/cfcanaoj/MHDTurbulence.git
artdir=artifacts

echo "[${code}] Building on system: $system"

mkdir -p ${artdir}

if [ ! -d "$code" ]; then
    git clone $REPO
fi

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
