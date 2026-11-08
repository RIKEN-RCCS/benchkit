#!/bin/bash
# shellcheck disable=SC2155
set -e
system="$1"
nodes="$2"
source scripts/bk_functions.sh
RESULTS="$PWD/results"
mkdir -p "$RESULTS"
: > "$RESULTS/result"
bk_use_runtime --allow-artifacts
bin_dir=$(bk_runtime_path scale/scale-letkf/scale/ensmodel bin)
letkf_bin=$(bk_runtime_path scale/scale-letkf/scale/letkf/letkf bin/letkf)

benchmark=benchmark.RC_GH200_128x128
pp_ranks=4
ranks=12
threads=1
mpi_options=(--oversubscribe)
mpi_output=""
input_root=""
use_mps=false
case "$system" in
  Fugaku|FugakuCN)
    SCALE_DATABASE="/vol0500/share/ra250029/CX_input/SCALE-LETKF/scale_database.tar.gz"
    SCALE_TESTDATA="/vol0500/share/ra250029/CX_input/SCALE-LETKF/SCALE-LETKF.dataset-SC23.part1.20240410.tar.gz"
    case "$nodes" in
      3) benchmark=benchmark.Fugaku_128x128 ;;
      75) benchmark=benchmark.Fugaku_1280x1280; pp_ranks=100; ranks=300 ;;
      *) echo 'SCALE Fugaku requires 3 or 75 nodes' >&2; exit 2 ;;
    esac
    threads=12
    mpi_options=()
    mpi_output=log/NOUT_
    export FORT90L=-Wl,-T PLE_MPI_STD_EMPTYFILE=off
    export LD_LIBRARY_PATH=/lib64:/opt/FJSVxtclanga/tcsds-mpi-latest/lib64:/opt/FJSVxtclanga/tcsds-latest/lib64:`cat /home/apps/oss/scale/llio.list | sed 's:\(.*/lib\)/.*:\1:' | uniq | sed -z 's/\n/:/g'`
    ;;
  RC_GH200)
    [[ "$nodes" == 1 ]] || exit 2
    SCALE_DATABASE="/lvs0/rccs-sdt/tyamaura/tgz-archive/scale_database.tar.gz"
    SCALE_TESTDATA="/lvs0/rccs-sdt/tyamaura/tgz-archive/SCALE-LETKF.dataset-SC23.part1.20240410.tar.gz"
    if ! type module >/dev/null 2>&1; then source /etc/profile.d/modules.sh; fi
    module purge
    module load nvhpc-hpcx/26.9
    source "$BK_RUNTIME_DIR/setup-env.RC_GH200.sh"
    ;;
  RIKYU)
    [[ "$nodes" == 1 && "$3" == 1 && "$4" =~ ^[0-9]+$ && "$4" -ge 12 ]] || exit 2
    module load "${SCALE_LETKF_MODULE:-nvhpc-hpcx/26.3}"
    nc="${SCALE_LETKF_NC_CONFIG:-nc-config}"
    nf="${SCALE_LETKF_NF_CONFIG:-nf-config}"
    command -v "$nc" >/dev/null && command -v "$nf" >/dev/null || exit 1
    LD_LIBRARY_PATH="$("$nf" --prefix)/lib:$("$nc" --prefix)/lib:${LD_LIBRARY_PATH:-}"
    export LD_LIBRARY_PATH
    input_root="${SCALE_LETKF_INPUT_ROOT:-/data1/rkp00015/CX_input/SCALE-LETKF}"
    use_mps=true
    ;;
  *) echo "Unknown system: $system" >&2; exit 1 ;;
esac
export OMP_NUM_THREADS="$threads" OMP_WAIT_POLICY=active
ulimit -s unlimited
exp="SC23_${benchmark##*_}"
work=$(mktemp -d "$PWD/scale-run.XXXXXXXX")
cp -a "$BK_RUNTIME_DIR/test/$benchmark/." "$work/"
cd "$work"
finish_run() {
    local status=$?
    trap - EXIT
    if [[ -d conf ]]; then cp -a conf "$RESULTS/configuration" || status=1; fi
    if [[ -d log ]]; then cp -a log "$RESULTS/application-logs" || status=1; fi
    exit "$status"
}
trap finish_run EXIT

if [[ -n "$input_root" ]]; then
    # Only read-only input fields use shared data; generated fields stay local.
    readonly_fields='BASENAME_ORG|OBS_IN_NAME|GTOPO30_IN_DIR|DEM50M_IN_DIR|GLCCV2_IN_DIR|LU100M_IN_DIR'
    shared_sed=$(printf '%s' "$input_root" | sed 's/[\\&#]/\\&/g')
    sed -E -i "/^[[:space:]]*($readonly_fields)[[:space:]]*=/I s#<--WKDIR-->#$shared_sed#g" template/*.conf
fi
bash prep.sh
if [[ -n "$input_root" ]]; then
    [[ -d "$input_root/scale_database" && -r "$input_root/result/SC23/obs_radar/radar_20210730060030.dat" ]] || exit 2
    for member in mean 0001 0002; do
        compgen -G "$input_root/result/SC23/20210730060000/bdyorg/$member/bdyorg*.nc" >/dev/null || exit 2
    done
    find conf -name '*.conf' -type f -exec awk -F '["\047]' \
        -v shared="$input_root/" -v fields="$readonly_fields" '
            index($2, shared) == 1 && toupper($1) !~ "^[[:space:]]*(" fields ")[[:space:]]*=" { exit 2 }
        ' {} +
else
    tar zxf "$SCALE_DATABASE"
    tar zxf "$SCALE_TESTDATA"
fi
for exe in scale-rm_pp_ens scale-rm_init_ens scale-rm_ens; do
    ln -s "$bin_dir/$exe" "bin/$exe"
done
ln -s "$letkf_bin" bin/letkf

run_benchmark() {
    local stage count date exe conf fom elapse_scale="" elapse_letkf=""
    local -a elapsed output
    for stage in pp init scale letkf; do
        count="$ranks"
        date=20210730060000
        elapsed=()
        case "$stage" in
            pp) exe=scale-rm_pp_ens; count="$pp_ranks" ;;
            init) exe=scale-rm_init_ens ;;
            scale) exe=scale-rm_ens; elapsed=(--elapsed elapse_scale) ;;
            letkf) exe=letkf; date=20210730060030; elapsed=(--elapsed elapse_letkf) ;;
        esac
        conf="conf/${exe}_${date}.conf"
        output=()
        if [[ -n "$mpi_output" ]]; then output=(-std-proc "$mpi_output$exe"); fi
        bk_run --input-file "$conf" --log "$RESULTS/$stage.log" "${elapsed[@]}" -- \
            mpiexec -n "$count" "${mpi_options[@]}" "${output[@]}" "bin/$exe" "$conf" || return
    done
    [[ -n "$elapse_scale" && -n "$elapse_letkf" ]] || return 1
    fom=$(awk -v s="$elapse_scale" -v l="$elapse_letkf" 'BEGIN { if (s+0 < 0 || l+0 < 0) exit 1; printf "%.3f", s+l }') || return
    bk_record_input --dataset-id "scale-letkf-sc23-${benchmark##*_}-${system,,}-config" \
        --result-exp "$exp" --path "$BK_RUNTIME_DIR/test/$benchmark" \
        --recipe 'Build-provided benchmark configuration.' || return
    if [[ -n "$input_root" ]]; then
        bk_record_input --dataset-id scale-letkf-sc23-rikyu --type dataset --version 20240410 --result-exp "$exp" \
            --recipe 'Expanded SC23 boundary and radar inputs read directly; generated fields remain local.' || return
    else
        bk_record_input --dataset-id scale-letkf-scale-database --type archive --result-exp "$exp" \
            --recipe 'SCALE database archive expanded before the benchmark run.' || return
        bk_record_input --dataset-id scale-letkf-sc23-part1-20240410 --type archive --version 20240410 --result-exp "$exp" \
            --recipe 'SC23 SCALE-LETKF benchmark dataset archive expanded before the benchmark run.' || return
    fi
    bk_emit_result --from-log "$RESULTS/scale.log" --from-log "$RESULTS/letkf.log" \
        --fom "$fom" --fom-unit s --fom-version SCALE-LETKF --exp "$exp" \
        --nodes "$nodes" --numproc-node "$((ranks / nodes))" --nthreads "$threads" >> "$RESULTS/result"
}

if "$use_mps"; then
    bk_with_mps run_benchmark
else
    run_benchmark
fi
