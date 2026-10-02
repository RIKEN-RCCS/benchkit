#!/bin/bash
# shellcheck disable=SC2155
set -e
system="$1"
nodes="$2"
elapse_scale=""
elapse_letkf=""
mkdir -p results && : > results/result

source "${PWD}/scripts/bk_functions.sh"

case "$system" in
  Fugaku|FugakuCN)

    SCALE_DATABASE="/vol0500/share/ra250029/CX_input/SCALE-LETKF/scale_database.tar.gz"
    SCALE_TESTDATA="/vol0500/share/ra250029/CX_input/SCALE-LETKF/SCALE-LETKF.dataset-SC23.part1.20240410.tar.gz"
    TESTDIR="benchmark.scale-letkf.Fugaku"

    export OMP_NUM_THREADS=12
    export FORT90L=-Wl,-T
    export PLE_MPI_STD_EMPTYFILE=off
    export OMP_WAIT_POLICY=active
    export LD_LIBRARY_PATH=/lib64:/opt/FJSVxtclanga/tcsds-mpi-latest/lib64:/opt/FJSVxtclanga/tcsds-latest/lib64:`cat /home/apps/oss/scale/llio.list | sed 's:\(.*/lib\)/.*:\1:' | uniq | sed -z 's/\n/:/g'`

    case "$nodes" in
      3)
        echo "copy essential files ... `date`"
        cp -a artifacts/test/benchmark.Fugaku_128x128 $TESTDIR
        cd $TESTDIR
        bash prep.sh
        cp -a ../artifacts/bin/scale-rm_pp_ens bin/
        cp -a ../artifacts/bin/scale-rm_init_ens bin/
        cp -a ../artifacts/bin/scale-rm_ens bin/
        cp -a ../artifacts/bin/letkf bin/
        echo "expand database archive ... `date`"
        tar zxf $SCALE_DATABASE
        echo "expand testdata archive ... `date`"
        tar zxf $SCALE_TESTDATA

        # SCALE-RM-PP
        echo "SCALE-RM_PP run starting ... `date`"
        mpiexec -n 4 -std-proc log/NOUT_scale-rm_pp_ens bin/scale-rm_pp_ens conf/scale-rm_pp_ens_20210730060000.conf
        # SCALE-RM-INIT
        echo "SCALE-RM_INIT run starting ... `date`"
        mpiexec -n 12 -std-proc log/NOUT_scale-rm_init_ens bin/scale-rm_init_ens conf/scale-rm_init_ens_20210730060000.conf

        # SCALE-RM
        echo "SCALE-RM   run starting ... `date`"
        bk_run --log scale.log --elapsed elapse_scale -- mpiexec -n 12 -std-proc log/NOUT_scale-rm_ens bin/scale-rm_ens conf/scale-rm_ens_20210730060000.conf
        echo "SCALE-RM   run ending ... elapse ($elapse_scale sec)"

        # LETKF
        echo "LETKF      run starting ... `date`"
        bk_run --log letkf.log --elapsed elapse_letkf -- mpiexec -n 12 -std-proc log/NOUT_letkf bin/letkf conf/letkf_20210730060030.conf
        echo "LETKF      run ending ... elapse ($elapse_letkf sec)"

        FOM=$(echo "$elapse_scale $elapse_letkf" | awk '{printf "%.3f\n", $1 + $2}')
        bk_record_input \
          --dataset-id scale-letkf-sc23-128x128-fugaku-config \
          --result-exp SC23_128x128 \
          --path test/benchmark.Fugaku_128x128 \
          --recipe "Benchmark configuration copied from the source repository artifacts."
        bk_record_input \
          --dataset-id scale-letkf-scale-database \
          --type archive \
          --result-exp SC23_128x128 \
          --recipe "SCALE database archive expanded before the benchmark run."
        bk_record_input \
          --dataset-id scale-letkf-sc23-part1-20240410 \
          --version 20240410 \
          --type archive \
          --result-exp SC23_128x128 \
          --recipe "SC23 SCALE-LETKF benchmark dataset archive expanded before the benchmark run."
        bk_emit_result --from-log scale.log --from-log letkf.log --fom "$FOM" --fom-unit s --fom-version SCALE-LETKF --exp SC23_128x128 --nodes "$nodes"  --numproc-node 4 --nthreads 12 >> ../results/result
      ;;
      75)
        echo "copy essential files ... `date`"
        cp -a artifacts/test/benchmark.Fugaku_1280x1280 $TESTDIR
        cd $TESTDIR
        bash prep.sh
        cp -a ../artifacts/bin/scale-rm_pp_ens bin/
        cp -a ../artifacts/bin/scale-rm_init_ens bin/
        cp -a ../artifacts/bin/scale-rm_ens bin/
        cp -a ../artifacts/bin/letkf bin/
        echo "expand database archive ... `date`"
        tar zxf $SCALE_DATABASE
        echo "expand testdata archive ... `date`"
        tar zxf $SCALE_TESTDATA

        # SCALE-RM-PP
        echo "SCALE-RM_PP run starting ... `date`"
        mpiexec -n 100 -std-proc log/NOUT_scale-rm_pp_ens bin/scale-rm_pp_ens conf/scale-rm_pp_ens_20210730060000.conf
        # SCALE-RM-INIT
        echo "SCALE-RM_INIT run starting ... `date`"
        mpiexec -n 300 -std-proc log/NOUT_scale-rm_init_ens bin/scale-rm_init_ens conf/scale-rm_init_ens_20210730060000.conf

        # SCALE-RM
        echo "SCALE-RM   run starting ... `date`"
        bk_run --log scale.log --elapsed elapse_scale -- mpiexec -n 300 -std-proc log/NOUT_scale-rm_ens bin/scale-rm_ens conf/scale-rm_ens_20210730060000.conf
        echo "SCALE-RM   run ending ... elapse ($elapse_scale sec)"

        # LETKF
        echo "LETKF      run starting ... `date`"
        bk_run --log letkf.log --elapsed elapse_letkf -- mpiexec -n 300 -std-proc log/NOUT_letkf bin/letkf conf/letkf_20210730060030.conf
        echo "LETKF      run ending ... elapse ($elapse_letkf sec)"

        FOM=$(echo "$elapse_scale $elapse_letkf" | awk '{printf "%.3f\n", $1 + $2}')
        bk_record_input \
          --dataset-id scale-letkf-sc23-1280x1280-fugaku-config \
          --result-exp SC23_1280x1280 \
          --path test/benchmark.Fugaku_1280x1280 \
          --recipe "Benchmark configuration copied from the source repository artifacts."
        bk_record_input \
          --dataset-id scale-letkf-scale-database \
          --type archive \
          --result-exp SC23_1280x1280 \
          --recipe "SCALE database archive expanded before the benchmark run."
        bk_record_input \
          --dataset-id scale-letkf-sc23-part1-20240410 \
          --version 20240410 \
          --type archive \
          --result-exp SC23_1280x1280 \
          --recipe "SC23 SCALE-LETKF benchmark dataset archive expanded before the benchmark run."
        bk_emit_result --from-log scale.log --from-log letkf.log --fom "$FOM" --fom-unit s --fom-version SCALE-LETKF --exp SC23_1280x1280 --nodes "$nodes" --numproc-node 4 --nthreads 12 >> ../results/result
      ;;
    esac
  ;;
  RC_GH200)

    SCALE_DATABASE="/lvs0/rccs-sdt/tyamaura/tgz-archive/scale_database.tar.gz"
    SCALE_TESTDATA="/lvs0/rccs-sdt/tyamaura/tgz-archive/SCALE-LETKF.dataset-SC23.part1.20240410.tar.gz"
    TESTDIR="benchmark.scale-letkf.RC_GH200"

    module purge
    module load system/qc-gh200
    module load nvhpc/25.9

    source artifacts/setup-env.RC_GH200.sh
    export OMP_NUM_THREADS=1

    case "$nodes" in
      1)
        echo "copy essential files ... `date`"
        cp -a artifacts/test/benchmark.RC_GH200_128x128 $TESTDIR
        cd $TESTDIR
        bash prep.sh
        cp -a ../artifacts/bin/scale-rm_pp_ens bin/
        cp -a ../artifacts/bin/scale-rm_init_ens bin/
        cp -a ../artifacts/bin/scale-rm_ens bin/
        cp -a ../artifacts/bin/letkf bin/
        echo "expand database archive ... `date`"
        tar zxf $SCALE_DATABASE
        echo "expand testdata archive ... `date`"
        tar zxf $SCALE_TESTDATA

        # SCALE-RM-PP
        echo "SCALE-RM_PP run starting ... `date`"
        mpiexec -n 4 --oversubscribe bin/scale-rm_pp_ens conf/scale-rm_pp_ens_20210730060000.conf
        # SCALE-RM-INIT
        echo "SCALE-RM_INIT run starting ... `date`"
        mpiexec -n 12 --oversubscribe bin/scale-rm_init_ens conf/scale-rm_init_ens_20210730060000.conf

        # SCALE-RM
        echo "SCALE-RM   run starting ... `date`"
        bk_run --log scale.log --elapsed elapse_scale -- mpiexec -n 12 --oversubscribe bin/scale-rm_ens conf/scale-rm_ens_20210730060000.conf
        echo "SCALE-RM   run ending ... elapse ($elapse_scale sec)"

        # LETKF
        echo "LETKF      run starting ... `date`"
        bk_run --log letkf.log --elapsed elapse_letkf -- mpiexec -n 12 --oversubscribe bin/letkf conf/letkf_20210730060030.conf
        echo "LETKF      run ending ... elapse ($elapse_letkf sec)"

        FOM=$(echo "$elapse_scale $elapse_letkf" | awk '{printf "%.3f\n", $1 + $2}')
        bk_record_input \
          --dataset-id scale-letkf-sc23-128x128-rc-gh200-config \
          --result-exp SC23_128x128 \
          --path test/benchmark.RC_GH200_128x128 \
          --recipe "Benchmark configuration copied from the source repository artifacts."
        bk_record_input \
          --dataset-id scale-letkf-scale-database \
          --type archive \
          --result-exp SC23_128x128 \
          --recipe "SCALE database archive expanded before the benchmark run."
        bk_record_input \
          --dataset-id scale-letkf-sc23-part1-20240410 \
          --version 20240410 \
          --type archive \
          --result-exp SC23_128x128 \
          --recipe "SC23 SCALE-LETKF benchmark dataset archive expanded before the benchmark run."
        bk_emit_result --from-log scale.log --from-log letkf.log --fom "$FOM" --fom-unit s --fom-version SCALE-LETKF --exp SC23_128x128 --nodes "$nodes" --numproc-node 12 --nthreads 1 >> ../results/result
      ;;
    esac
  ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
  ;;
esac
