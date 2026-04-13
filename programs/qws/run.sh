#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
export OMP_NUM_THREADS=$nthreads

source "${PWD}/scripts/bk_functions.sh"
qws_profiler_tool="fapp"
qws_profiler_level="simple"
# Load estimation helpers used when emitting section/overlap metadata.
source "${PWD}/programs/qws/estimate.sh"

mkdir -p results && > results/result

# print_results: extract FOM from the benchmark output and append a result line.
print_results() {
    local outfile=$1
    local exp=$2
    local np=$3
    ./check.sh "$outfile" "data/$exp"
    local fom
    fom=$(grep etime "$outfile" | awk 'NR==2{printf("%5.3f\n",$5)}')
    bk_emit_result --fom "$fom" --fom-version DDSolverJacobi --exp "$exp" --nodes "$nodes" --numproc-node "$np" --nthreads "$nthreads"
    qws_emit_estimation_data_from_fom "$fom"
}

resolve_latest_fugaku_stdout() {
    local stdout_name=$1
    local output_root="output.${PJM_JOBID}/0"
    local candidate
    local latest=""

    shopt -s nullglob
    for candidate in "${output_root}"/*/"${stdout_name}"; do
        latest="$candidate"
    done
    shopt -u nullglob

    if [[ -z "$latest" ]]; then
        echo "ERROR: could not resolve Fugaku stdout path for ${stdout_name} under ${output_root}" >&2
        return 1
    fi

    printf '%s\n' "$latest"
}

emit_qws_dummy_padata() {
    mkdir -p pa
    echo dummy > ./pa/padat.0
    echo dummy > ./pa/padat.1
    echo dummy > ./pa/padat.2
    echo dummy > ./pa/padat.3
    tar -czf "$1" ./pa
}

[[ -d qws ]] || git clone https://github.com/RIKEN-LQCD/qws.git

if [[ -f artifacts/main ]]; then
    cp artifacts/main qws
else
    echo "ERROR: artifacts/main not found"
    exit 1
fi

cd qws

case "$system" in
    Fugaku|FugakuCN)
        case "$nodes" in
            1)
                bk_profiler "$qws_profiler_tool" --level "$qws_profiler_level" --archive ../results/padata0.tgz --raw-dir pa -- mpiexec -n 1 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
                print_results "$(resolve_latest_fugaku_stdout stdout.1.0)" CASE0 1 >> ../results/result
                if ! bk_profiler_enabled "$qws_profiler_tool"; then
                    emit_qws_dummy_padata ../results/padata0.tgz
                fi
                mpiexec -n 2 ./main 32 6 4 3 1 1 1 2 -1 -1 6 50 > CASE1
                print_results "$(resolve_latest_fugaku_stdout stdout.2.0)" CASE1 2 >> ../results/result
                ;;
            2)
                bk_profiler "$qws_profiler_tool" --level "$qws_profiler_level" --archive ../results/padata0.tgz --raw-dir pa -- mpiexec -n 8 ./main 32 6 4 3 1 2 2 2 -1 -1 6 50 > CASE7
                print_results "$(resolve_latest_fugaku_stdout stdout.1.0)" CASE7 4 >> ../results/result
                if ! bk_profiler_enabled "$qws_profiler_tool"; then
                    emit_qws_dummy_padata ../results/padata0.tgz
                fi
                ;;
            *)
                echo "Undefined node numbers for system: $system"
                exit 1
                ;;
        esac
        ;;
    FugakuLN)
        echo 'dummy call for CI test: QWS program: ./main 32 6 4 3 1 1 1 1 -1 -1 6 50'
        bk_emit_result --fom 123.56 --fom-version dummy --exp CheckingPrivateRepo --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
        emit_qws_dummy_padata ../results/padata0.tgz
        ;;
    FNCX)
        echo 'dummy call for FNCX Docker runner test'
        bk_emit_result --fom 99.99 --fom-version dummy --exp FNCXTest --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
        ;;
    RC_GH200)
        module load system/qc-gh200 nvhpc-hpcx/25.9
        mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=72 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    RC_GENOA)
        module load system/genoa mpi/openmpi-x86_64
        mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=96 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    RC_DGXSP)
        source /etc/profile.d/modules.sh
        module load system/ng-dgx nvhpc-hpcx/26.3
        mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=20 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    RC_FX700)
        module load system/fx700 FJSVstclanga
        mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=12 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    MiyabiG|MiyabiC)
        mpirun -n 1 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    *)
        echo "Unknown Running system: $system"
        exit 1
        ;;
esac

cd ..
sync
sleep 5
