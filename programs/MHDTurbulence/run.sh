#!/bin/bash
# usage: bash scripts/test_submit.sh MHDTurbulence n

set -eux
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"

code=MHDTurbulence
artdir=artifacts
BIN=Simulation.x

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p results

LOG=stdout.log
case "$system" in
    MiyabiC)
	exedir=exe
	mkdir -p $code/$exedir/
	cp $artdir/${BIN} $code/$exedir/
	cd $code/$exedir/
	echo "code is executed in "$code/$exedir/
	NP=$((nodes * numproc_node))
	export OMP_NUM_THREADS=$nthreads
	export KMP_AFFINITY=compact
	mpirun -np "$NP" ./Simulation.x > ${LOG} 2>&1
	elapsed=$(grep "sim time \[s\]:" ${LOG} | awk '{print $4}' | tail -n 1)
	tcc=$(grep "time/count/cell" ${LOG} | awk '{print $2}' | tail -n 1)
	;;
    MiyabiG)
	exedir=exe
	mkdir -p $code/$exedir/
	cp $artdir/${BIN} $code/$exedir/
	cd $code/$exedir/
	echo "code is executed in "$code/$exedir/
	NP=$((nodes * numproc_node))
	mpirun -np "$NP" ./Simulation.x > ${LOG} 2>&1
	elapsed=$(grep "sim time \[s\]:" ${LOG} | awk '{print $4}' | tail -n 1)
	tcc=$(grep "time/count/cell" ${LOG} | awk '{print $2}' | tail -n 1)
	;;
    *)
	echo "Unknown system: $system"
	exit 1
	;;
esac


if [ -z "${elapsed}" ]; then
  echo "ERROR: elapsed time was not found in ${LOG}"
  exit 1
fi

if [ -z "${tcc}" ]; then
  echo "ERROR: time/count/cell was not found in ${LOG}"
  exit 1
fi

cd ${ROOT}
source "${ROOT}/scripts/bk_functions.sh"

fomtcc=$(awk "BEGIN {printf \"%.6e\", 1.0/$tcc}")


########################################
# emit benchkit result
########################################
{
  bk_emit_result \
    --fom "$fomtcc" \
    --fom-version "cell_updates_per_sec" \
    --exp "KH" \
    --nodes "$nodes" \
    --numproc-node "$numproc_node" \
    --nthreads "$nthreads"

  bk_emit_section total "$elapsed"
} > "${ROOT}/results/result"
