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
result_log_args=()
case "$system" in
    Camphor3)
        module switch PrgEnvIntel PrgEnvIntel/2023
        [[ "$nodes" == 1 && "$numproc_node" == 96 && "$nthreads" == 1 ]] || { echo "Camphor3 MHD input requires 1 node, 96 ranks, 1 thread" >&2; exit 1; }
        mkdir -p results/mhd_run
        cp artifacts/Simulation.x artifacts/mhd_cpu_input/config.f90 artifacts/mhd_cpu_input/main.f90 results/mhd_run/
        source "$ROOT/scripts/bk_functions.sh"
        bk_record_input --dataset-id mhd-kh --directory artifacts/mhd_cpu_input --recipe "Compiled-in CPU config and initial conditions; unchanged upstream KH problem"
        cd results/mhd_run
        export OMP_NUM_THREADS=1 OMP_PLACES=cores OMP_PROC_BIND=close
        bk_run --log "$LOG" -- srun -n 96 --ntasks-per-node=96 --cpus-per-task=1 ./Simulation.x
        bash "$ROOT/programs/MHDTurbulence/validate_cpu_run.sh" "$LOG" t-prof.csv config.f90
        result_log_args=(--from-log "$ROOT/results/mhd_run/$LOG")
        elapsed=$(grep "sim time \[s\]:" "$LOG" | awk '{print $4}' | tail -n 1)
        tcc=$(grep "time/count/cell" "$LOG" | awk '{print $2}' | tail -n 1)
        ;;
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
  bk_emit_result "${result_log_args[@]}" \
    --fom "$fomtcc" \
    --fom-unit cell/s \
    --fom-version "cell_updates_per_sec" \
    --exp "KH" \
    --nodes "$nodes" \
    --numproc-node "$numproc_node" \
    --nthreads "$nthreads"

  bk_emit_section total "$elapsed"
} > "${ROOT}/results/result"
