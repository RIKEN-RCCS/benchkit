#!/bin/bash
set -euo pipefail
[[ "$1" == RIKYU && "$2" == 1 && "$3" == 1 && "$4" =~ ^[0-9]+$ && "$4" -ge 12 ]] || {
    echo 'RIKYU SCALE requires one node, one launch task and at least 12 allocated CPUs' >&2; exit 2;
}
APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$APP_DIR/runtime-rikyu.sh"
scale_rikyu_environment
source scripts/bk_functions.sh
bk_use_runtime
ROOT=$PWD
RESULTS="$ROOT/results"
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
bash prep.sh
python3 "$APP_DIR/prepare-rikyu.py" configure "$work" "$shared"
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
