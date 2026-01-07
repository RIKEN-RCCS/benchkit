#!/bin/bash
set -e
system="$1"
nodes="$2"
mkdir -p results && > results/result

TARDIR=./
case "$system" in
  Fugaku*)
    TARDIR=/vol0004/share/ra000001/kanamori/benchkit
    ;;
  Miyabi*)
    TARDIR=/home/q49000/benchkit_appsrc
    ;;
  *)
    ;;
esac
echo "soruce location " $TARDIR

TARBALL=LQCD_dw_solver_20251209_773762.tar.gz
SRC=`echo $TARBALL|sed -e "s/\.tar\.gz//"`
DIR=LQCD_dw_solver
echo "[LQCD_dw_solver] Running on system: $system"
if [ ! -e $DIR ]; then
  cp $TARDIR/$TARBALL .
  tar -zxf $TARBALL
  ln -s $SRC $DIR
fi

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
  #echo FOM:${FOM1}" : "${FOM2} > ../../results/result
  if [ $# -ne 1 ]; then
      echo FOM:${FOM1}" : "${FOM2}
  else
      echo FOM:${FOM1}" : "${FOM2} $2
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

}

case "$system" in
  Fugaku|FugakuCN)
    case "$nodes" in
      1)
        cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,2,2/" -e "s/xxx_number_of_thread_xxx/12/" > main.yaml
        export OMP_NUM_THREADS=12
        export FLIB_BARRIER=HARD
        mpiexec -np 4 -std-proc run.log $BIN alt_qxs
        this_log=`ls ./run.log.*.0|tail -n 1`
	[[ -f $this_log ]] && cp $this_log run.log
        check run.log
        get_fom run.log >> $RESULT
        ;;
      12)
        cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,16,16,24/" -e "s/xxx_grid_size_xxx/2,2,4,3/" -e "s/xxx_number_of_thread_xxx/12/" > main.yaml
        export OMP_NUM_THREADS=12
        export FLIB_BARRIER=HARD
        mpiexec -np 48 -std-proc run.log $BIN alt_qxs
        this_log=`./run.log.*.0|tail -n 1`
	[[ -f $this_log ]] && cp this_log run.log
        check run.log
        get_fom run.log >> $RESULT
        ;;
      *)
        echo "Unknown number of nodes: $nodes"

        exit 1
        ;;
      esac
      ;;
  FugakuLN )
      echo 'dummy call for CB test: LQCD-dw-solver'
      echo FOM: 123 : 456 > $RESULT
      ;;
  MiyabiG )
      # openacc
      cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,1,1/" -e "s/xxx_number_of_thread_xxx/2/" > main.yaml
      mpiexec -np 1 ./bridge_openacc.elf alt_accel > run.log
      check run.log
      get_fom run.log "target: OpenACC " > $RESULT
      mpiexec -np 1 ./bridge_cuda.elf alt_accel > run_cuda.log
      check run_cuda.log
      get_fom run_cuda.log "target: CUCA" >> $RESULT
      ;;
  MiyabiC )
      cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,1,2/" -e "s/xxx_number_of_thread_xxx/56/" > main.yaml
      mpiexec -np 2 ./bridge.elf alt_simd > run.log
      check run.log
      get_fom run.log >> $RESULT
      ;;
  AVX512 )
      cat main_template.yaml |sed -e "s/xxx_lattice_size_xxx/32,8,8,12/" -e "s/xxx_grid_size_xxx/1,1,1,1/" -e "s/xxx_number_of_thread_xxx/8/" > main.yaml
      mpiexec -np 1 ./bridge.elf alt_simd > run.log
      check run.log
      get_fom run.log >> $RESULT
      ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
    ;;
esac
