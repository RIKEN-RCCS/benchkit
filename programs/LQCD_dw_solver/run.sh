#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
export OMP_NUM_THREADS=$nthreads
mkdir -p results && : > results/result

source "${PWD}/scripts/bk_functions.sh"

echo "[LQCD_dw_solver] Running on system: $system"
RESULT="$PWD/results/result"
bk_use_runtime
cd "$BK_RUNTIME_DIR/run"

get_fom() {
  local log="$1" exp="${2:-total}" solver total other
  solver=$(grep -A 1 'solver performance:' "$log" | tail -n 1 | sed -e 's/^.*=//' -e 's/sec//' -e 's/ //g')
  total=$(grep 'Elapsed time: Spectrum_Domainwall_alt.hadron_2ptFunction: total' "$log" | sed -e 's/^.*total *//' -e 's/sec.*$//' -e 's/ //g')
  other=$(awk -v total="$total" -v solver="$solver" 'BEGIN {print total-solver}')
  bk_emit_result --from-log "$log" --fom "$total" --fom-unit s --fom-version LQCD_dw_solver --exp "$exp" --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads"
  bk_emit_section solver "$solver"
  bk_emit_section other "$other"
}

check () {
  local LOG="$1" check check1 check2 check3 result
  check=`grep "Richardson  nconv " "$LOG" | awk 'BEGIN {s=0;i=0;err=0} {s=(s<$7)?$7:s; i+=1; if(0+$7 == 0){err+=1}} END {print i, s, err}'`
  echo "check low prec solver: " $check
  check1=`echo $check |awk '{ if($1 !=12 ){print 1} }'`
  check2=`echo $check |awk '{ if($2 >1e-26 ){print 2} }'`
  check3=`echo $check |awk '{ if($3 > 0 ){print 4} }'`

  result=$((check1+check2+check3))
  echo "check result " $result
  return "$result"

}

# Site differences define the scientific input and launcher; execution is shared.
lattice=32,8,8,12
grid=1,1,1,1
input_threads="$nthreads"
launcher=(mpiexec -np 1)
binaries=(./bridge.elf)
logs=(run.log)
experiments=(total)
mode=alt_simd
case "$system" in
  Fugaku|FugakuCN)
    case "$nodes" in
      1) grid=1,1,2,2; ranks=4 ;;
      12) lattice=32,16,16,24; grid=2,2,4,3; ranks=48 ;;
      *) echo "Unknown number of nodes: $nodes" >&2; exit 1 ;;
    esac
    input_threads=12
    export OMP_NUM_THREADS=12 FLIB_BARRIER=HARD
    launcher=(mpiexec -np "$ranks" -stdout-proc stdout -stderr-proc stderr)
    mode=alt_qxs
    ;;
  MiyabiG|RIKYU)
    binaries=(./bridge_openacc.elf ./bridge_cuda.elf)
    logs=(run.log run_cuda.log)
    experiments=(total_OpenACC total_CUDA)
    mode=alt_accel
    if [ "$system" = RIKYU ]; then
      module load nvhpc-hpcx/26.3
      # One rank uses one GPU, selected by OMPI_COMM_WORLD_LOCAL_RANK.
      launcher=(mpirun -np 1 --bind-to none)
    else
      input_threads=2
      # Preserve the existing experiment name used by this site's results.
      experiments=(total_OpenACC total_CUCA)
    fi
    ;;
  MiyabiC) grid=1,1,1,2; input_threads=56; launcher=(mpiexec -np 2) ;;
  AVX512) input_threads=8 ;;
  *) echo "Unknown Running system: $system" >&2; exit 1 ;;
esac

sed -e "s/xxx_lattice_size_xxx/$lattice/" \
    -e "s/xxx_grid_size_xxx/$grid/" \
    -e "s/xxx_number_of_thread_xxx/$input_threads/" main_template.yaml > main.yaml

for index in "${!binaries[@]}"; do
  log="${logs[$index]}"
  bk_run --log "$log" --input-file main.yaml -- "${launcher[@]}" "${binaries[$index]}" "$mode"
  check "$log"
  get_fom "$log" "${experiments[$index]}" >> "$RESULT"
done
