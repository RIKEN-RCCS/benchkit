#!/bin/bash
set -e
system="$1"
nodes="$2"
mkdir -p results && > results/result

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
        cp -a artifacts/scale-letkf-FugakuNEXT/test/benchmark.Fugaku_128x128 $TESTDIR
        cd $TESTDIR
        bash prep.sh
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_pp_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_init_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/letkf/letkf bin/
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
        startms=$(date +'%s.%3N')
        mpiexec -n 12 -std-proc log/NOUT_scale-rm_ens bin/scale-rm_ens conf/scale-rm_ens_20210730060000.conf
        endms=$(date +'%s.%3N')
        elapse=$(echo "$endms $startms" | awk '{printf "%.3f\n", $1 - $2}')
        echo "SCALE-RM   run ending ... elapse (`echo $elapse` sec)"
        elapse_scale=$elapse

        # LETKF
        echo "LETKF      run starting ... `date`"
        startms=$(date +'%s.%3N')
        mpiexec -n 12 -std-proc log/NOUT_letkf bin/letkf conf/letkf_20210730060030.conf
        endms=$(date +'%s.%3N')
        elapse=$(echo "$endms $startms" | awk '{printf "%.3f\n", $1 - $2}')
        echo "LETKF      run ending ... elapse (`echo $elapse` sec)"
        elapse_letkf=$elapse

        FOM=$(echo "$elapse_scale $elapse_letkf" | awk '{printf "%.3f\n", $1 + $2}')
        echo FOM:$FOM FOM_version:SCALE-LETKF Exp:SC23_128x128 node_count:$nodes >> ../results/result
      ;;
      75)
        echo "copy essential files ... `date`"
        cp -a artifacts/scale-letkf-FugakuNEXT/test/benchmark.Fugaku_1280x1280 $TESTDIR
        cd $TESTDIR
        bash prep.sh
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_pp_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_init_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/letkf/letkf bin/
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
        startms=$(date +'%s.%3N')
        mpiexec -n 300 -std-proc log/NOUT_scale-rm_ens bin/scale-rm_ens conf/scale-rm_ens_20210730060000.conf
        endms=$(date +'%s.%3N')
        elapse=$(echo "$endms $startms" | awk '{printf "%.3f\n", $1 - $2}')
        echo "SCALE-RM   run ending ... elapse (`echo $elapse` sec)"
        elapse_scale=$elapse

        # LETKF
        echo "LETKF      run starting ... `date`"
        startms=$(date +'%s.%3N')
        mpiexec -n 300 -std-proc log/NOUT_letkf bin/letkf conf/letkf_20210730060030.conf
        endms=$(date +'%s.%3N')
        elapse=$(echo "$endms $startms" | awk '{printf "%.3f\n", $1 - $2}')
        echo "LETKF      run ending ... elapse (`echo $elapse` sec)"
        elapse_letkf=$elapse

        FOM=$(echo "$elapse_scale $elapse_letkf" | awk '{printf "%.3f\n", $1 + $2}')
        echo FOM:$FOM FOM_version:SCALE-LETKF Exp:SC23_1280x1280 node_count:$nodes >> ../results/result
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

    source artifacts/scale-letkf-FugakuNEXT/setup-env.RC_GH200.sh
    export OMP_NUM_THREADS=1

    case "$nodes" in
      1)
        echo "copy essential files ... `date`"
        cp -a artifacts/scale-letkf-FugakuNEXT/test/benchmark.RC_GH200_128x128 $TESTDIR
        cd $TESTDIR
        bash prep.sh
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_pp_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_init_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/ensmodel/scale-rm_ens bin/
        cp -a ../artifacts/scale-letkf-FugakuNEXT/scale/scale-letkf/scale/letkf/letkf bin/
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
        startms=$(date +'%s.%3N')
        mpiexec -n 12 --oversubscribe bin/scale-rm_ens conf/scale-rm_ens_20210730060000.conf
        endms=$(date +'%s.%3N')
        elapse=$(echo "$endms $startms" | awk '{printf "%.3f\n", $1 - $2}')
        echo "SCALE-RM   run ending ... elapse (`echo $elapse` sec)"
        elapse_scale=$elapse

        # LETKF
        echo "LETKF      run starting ... `date`"
        startms=$(date +'%s.%3N')
        mpiexec -n 12 --oversubscribe bin/letkf conf/letkf_20210730060030.conf
        endms=$(date +'%s.%3N')
        elapse=$(echo "$endms $startms" | awk '{printf "%.3f\n", $1 - $2}')
        echo "LETKF      run ending ... elapse (`echo $elapse` sec)"
        elapse_letkf=$elapse

        FOM=$(echo "$elapse_scale $elapse_letkf" | awk '{printf "%.3f\n", $1 + $2}')
        echo FOM:$FOM FOM_version:SCALE-LETKF Exp:SC23_128x128 node_count:$nodes >> ../results/result
      ;;
    esac
  ;;
  *)
    echo "Unknown Running system: $system"
    exit 1
  ;;
esac
