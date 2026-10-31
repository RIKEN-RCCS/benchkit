#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
export OMP_NUM_THREADS=$nthreads
mkdir -p results && : > results/result

source "${PWD}/scripts/bk_functions.sh"

REPO_URL="${LQCD_DW_SOLVER_REPO_URL:-https://github.com/i-kanamori/LQCD-DWF-solver.git}"
DIR="LQCD_dw_solver"
BRANCH="${LQCD_DW_SOLVER_BRANCH:-main}"
SOURCE_COMMIT="${LQCD_DW_SOLVER_SOURCE_COMMIT:-}"

echo "[LQCD_dw_solver] Running on system: $system"
# run/main_template.yaml などソースツリー内の入力を使うため、
# build 時に記録した source_info と同じ commit を取得する
if [ -L "${DIR}" ] || { [ -e "${DIR}" ] && [ ! -d "${DIR}/.git" ]; }; then
  echo "[LQCD_dw_solver] Removing stale non-git source directory: ${DIR}"
  rm -rf "${DIR}"
fi
bk_fetch_recorded_source "${REPO_URL}" "${DIR}" "${BRANCH}" "${SOURCE_COMMIT}"

RESULT=../../results/result
cp artifacts/bridge*.elf $DIR/run/

cd $DIR/run
BIN=./bridge.elf

get_etime_total () {
  LOG=$1
  grep "Elapsed time: Spectrum_Domainwall_alt.hadron_2ptFunction: total" $LOG |sed -e "s/^.*total *//" -e "s/sec.*$//" -e "s/ //g"
}

get_etime_solver () {
  LOG=$1
  grep -A 1 "solver performance:" $LOG |tail -n 1 |sed -e "s/^.*=//" -e "s/sec//" -e "s/ //g"
}

get_fom () {
  LOG=$1
  FOM1=`get_etime_solver $LOG`
  FOM2=`get_etime_total $LOG`
  FOM_O=`echo $FOM2 $FOM1 | awk '{print $1-$2}'`
  if [ $# -eq 1 ]; then
      bk_emit_result --from-log "$LOG" --fom "$FOM2" --fom-unit s --fom-version LQCD_dw_solver --exp total --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads"
      bk_emit_section solver "$FOM1"
      bk_emit_section other "$FOM_O"
  else
      # 第2引数をExp名として使用
      # 注意: 暫定的にtarget情報をExpに付け加えます。
      TARGET=$(echo "$2" | sed 's/target: //' | sed 's/ $//')
      bk_emit_result --from-log "$LOG" --fom "$FOM2" --fom-unit s --fom-version LQCD_dw_solver --exp "total_${TARGET}" --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads"
      bk_emit_section solver "$FOM1"
      bk_emit_section other "$FOM_O"
  fi
}

check () {
  LOG=$1
  check=`grep "Richardson  nconv " $LOG | awk 'BEGIN {s=0;i=0;err=0} {s=(s<$7)?$7:s; i+=1; if(0+$7 == 0){err+=1}} END {print i, s, err}'`
  echo "check low prec solver: " $check
  check1=`echo $check |awk '{ if($1 !=12 ){print 1} }'`
  check2=`echo $check |awk '{ if($2 >1e-26 ){print 2} }'`
  check3=`echo $check |awk '{ if($3 > 0 ){print 4} }'`

  #echo "check1: " $check1
  #echo "check2: " $check2
  #echo "check3: " $check2
  result=$((check1+check2+check3))
  echo "check result " $result
  return "$result"

}

case "$system" in
  Fugaku|FugakuCN)
    case "$nodes" in
      1)
        cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,2,2/" -e "s/xxx_number_of_thread_xxx/12/" > main.yaml
        export OMP_NUM_THREADS=12
        export FLIB_BARRIER=HARD
        bk_run --log run.log -- mpiexec -np 4 -stdout-proc stdout -stderr-proc stderr $BIN alt_qxs
        check run.log
        get_fom run.log >> $RESULT
        ;;
      12)
        cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,16,16,24/" -e "s/xxx_grid_size_xxx/2,2,4,3/" -e "s/xxx_number_of_thread_xxx/12/" > main.yaml
        export OMP_NUM_THREADS=12
        export FLIB_BARRIER=HARD
        bk_run --log run.log -- mpiexec -np 48 -stdout-proc stdout -stderr-proc stderr $BIN alt_qxs
        check run.log
        get_fom run.log >> $RESULT
        ;;
      *)
        echo "Unknown number of nodes: $nodes"

        exit 1
        ;;
      esac
      ;;
  MiyabiG )
      # openacc
      cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,1,1/" -e "s/xxx_number_of_thread_xxx/2/" > main.yaml
      bk_run --log run.log -- mpiexec -np 1 ./bridge_openacc.elf alt_accel
      check run.log
      get_fom run.log "target: OpenACC " > $RESULT
      bk_run --log run_cuda.log -- mpiexec -np 1 ./bridge_cuda.elf alt_accel
      check run_cuda.log
      get_fom run_cuda.log "target: CUCA" >> $RESULT
      ;;
  RIKYU )
      module load nvhpc-hpcx/26.3
      # 1 rank = 1 GPU。GPU 割り当ては各 rank の OMPI_COMM_WORLD_LOCAL_RANK で行われる
      cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,1,1/" -e "s/xxx_number_of_thread_xxx/$nthreads/" > main.yaml
      bk_run --log run.log -- mpirun -np 1 --bind-to none ./bridge_openacc.elf alt_accel
      check run.log
      get_fom run.log "target: OpenACC " > $RESULT
      bk_run --log run_cuda.log -- mpirun -np 1 --bind-to none ./bridge_cuda.elf alt_accel
      check run_cuda.log
      get_fom run_cuda.log "target: CUDA" >> $RESULT
      ;;
  MiyabiC )
      cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,1,2/" -e "s/xxx_number_of_thread_xxx/56/" > main.yaml
      bk_run --log run.log -- mpiexec -np 2 ./bridge.elf alt_simd
      check run.log
      get_fom run.log >> $RESULT
      ;;
  AVX512 )
      cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,1,1/" -e "s/xxx_number_of_thread_xxx/8/" > main.yaml
      bk_run --log run.log -- mpiexec -np 1 ./bridge.elf alt_simd
      check run.log
      get_fom run.log >> $RESULT
      ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
    ;;
esac
