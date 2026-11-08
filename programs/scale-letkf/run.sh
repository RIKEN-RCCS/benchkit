#!/bin/bash
# shellcheck disable=SC2155
set -e
system="$1"
if [[ "$system" == RIKYU ]]; then
  set -euo pipefail
  [[ "$2" == 1 && "$3" == 1 && "$4" =~ ^[0-9]+$ && "$4" -ge 12 ]] || {
      echo 'RIKYU SCALE requires one node, one launch task and at least 12 allocated CPUs' >&2; exit 2;
  }
  module load "${SCALE_LETKF_MODULE:-nvhpc-hpcx/26.3}"
  nc="${SCALE_LETKF_NC_CONFIG:-nc-config}"
  nf="${SCALE_LETKF_NF_CONFIG:-nf-config}"
  command -v "$nc" >/dev/null && command -v "$nf" >/dev/null || exit 1
  LD_LIBRARY_PATH="$("$nf" --prefix)/lib:$("$nc" --prefix)/lib:${LD_LIBRARY_PATH:-}"
  export LD_LIBRARY_PATH
  source scripts/bk_functions.sh
  bk_use_runtime
  RESULTS="$PWD/results"
  mkdir -p "$RESULTS"
  : > "$RESULTS/result"
  shared="${SCALE_LETKF_INPUT_ROOT:-/data1/rkp00015/CX_input/SCALE-LETKF}"
  work=$(mktemp -d "$PWD/scale-rikyu.XXXXXXXX")
  cp -a "$BK_RUNTIME_DIR/test/benchmark.RC_GH200_128x128/." "$work/"
  cd "$work"
  mps_started=0
  finish_run() {
      local status=$?
      trap - EXIT
      if [[ -d conf ]]; then cp -a conf "$RESULTS/configuration" || status=1; fi
      if [[ -d log ]]; then cp -a log "$RESULTS/application-logs" || status=1; fi
      if [[ "$mps_started" == 1 ]]; then
          if printf 'quit\n' | nvidia-cuda-mps-control; then
              printf 'stopped\n' >> "$RESULTS/mps-lifecycle.log"
              rm -rf -- "$CUDA_MPS_PIPE_DIRECTORY"
          else
              echo 'SCALE MPS shutdown failed; diagnostic directories retained' >&2
              status=1
          fi
      fi
      exit "$status"
  }
  trap finish_run EXIT
  # Change only read-only input fields in the templates; prep.sh sets local outputs.
  readonly_fields='BASENAME_ORG|OBS_IN_NAME|GTOPO30_IN_DIR|DEM50M_IN_DIR|GLCCV2_IN_DIR|LU100M_IN_DIR'
  shared_sed=$(printf '%s' "$shared" | sed 's/[\\&#]/\\&/g')
  sed -E -i "/^[[:space:]]*($readonly_fields)[[:space:]]*=/I s#<--WKDIR-->#$shared_sed#g" template/*.conf
  bash prep.sh
  [[ -d "$shared/scale_database" && -r "$shared/result/SC23/obs_radar/radar_20210730060030.dat" ]]
  for member in mean 0001 0002; do
      compgen -G "$shared/result/SC23/20210730060000/bdyorg/$member/bdyorg*.nc" >/dev/null
  done
  find conf -name '*.conf' -type f -exec awk -F '["\047]' \
      -v shared="$shared/" -v fields="$readonly_fields" '
          index($2, shared) == 1 && toupper($1) !~ "^[[:space:]]*(" fields ")[[:space:]]*=" { exit 2 }
      ' {} +
  for exe in scale-rm_pp_ens scale-rm_init_ens scale-rm_ens; do
      ln -s "$BK_RUNTIME_DIR/scale/scale-letkf/scale/ensmodel/$exe" "bin/$exe"
  done
  ln -s "$BK_RUNTIME_DIR/scale/scale-letkf/scale/letkf/letkf" bin/letkf
  # The allocation is a CPU budget; the benchmark uses up to 12 single-threaded ranks.
  export OMP_NUM_THREADS=1 OMP_WAIT_POLICY=active
  ulimit -s unlimited
  # Use only the scheduler-assigned GPU, as a UUID to avoid MPS index remapping.
  device="${CUDA_VISIBLE_DEVICES:?A single allocated GPU is required}"
  [[ "$device" != *,* ]] || exit 2
  if [[ "$device" != GPU-* ]]; then
      device=$(nvidia-smi -i "$device" --query-gpu=uuid --format=csv,noheader)
  fi
  [[ "$device" == GPU-* && "$device" != *$'\n'* ]] || exit 2
  export CUDA_VISIBLE_DEVICES="$device"
  CUDA_MPS_PIPE_DIRECTORY=$(mktemp -d "${TMPDIR:-/tmp}/scale-mps.XXXXXXXX")
  CUDA_MPS_LOG_DIRECTORY="$RESULTS/mps"
  export CUDA_MPS_PIPE_DIRECTORY CUDA_MPS_LOG_DIRECTORY
  mkdir -p "$CUDA_MPS_LOG_DIRECTORY"
  mps_started=1
  nvidia-cuda-mps-control -d
  printf 'started\n' > "$RESULTS/mps-lifecycle.log"
  bk_run --input-file "conf/scale-rm_pp_ens_20210730060000.conf" --log "$RESULTS/pp.log" -- mpiexec -n 4 --oversubscribe bin/scale-rm_pp_ens conf/scale-rm_pp_ens_20210730060000.conf
  bk_run --input-file "conf/scale-rm_init_ens_20210730060000.conf" --log "$RESULTS/init.log" -- mpiexec -n 12 --oversubscribe bin/scale-rm_init_ens conf/scale-rm_init_ens_20210730060000.conf
  elapse_scale=""
  elapse_letkf=""
  bk_run --input-file "conf/scale-rm_ens_20210730060000.conf" --log "$RESULTS/scale.log" --elapsed elapse_scale -- mpiexec -n 12 --oversubscribe bin/scale-rm_ens conf/scale-rm_ens_20210730060000.conf
  bk_run --input-file "conf/letkf_20210730060030.conf" --log "$RESULTS/letkf.log" --elapsed elapse_letkf -- mpiexec -n 12 --oversubscribe bin/letkf conf/letkf_20210730060030.conf
  fom=$(awk -v s="$elapse_scale" -v l="$elapse_letkf" 'BEGIN { if (s+0 <= 0 || l+0 <= 0) exit 1; printf "%.3f", s+l }')
  bk_record_input --dataset-id scale-letkf-sc23-rikyu --type dataset --version 20240410 --result-exp SC23_128x128 \
      --recipe 'Expanded SC23 boundary and radar inputs read directly; generated fields remain local.'
  bk_emit_result --from-log "$RESULTS/scale.log" --from-log "$RESULTS/letkf.log" \
      --fom "$fom" --fom-unit s --fom-version SCALE-LETKF --exp SC23_128x128 \
      --nodes 1 --numproc-node 12 --nthreads 1 >> "$RESULTS/result"

  exit 0
fi
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

    if ! type module >/dev/null 2>&1; then
      source /etc/profile.d/modules.sh
    fi
    module purge
    module load nvhpc-hpcx/26.9

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
