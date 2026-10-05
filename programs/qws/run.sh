#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
export OMP_NUM_THREADS=$nthreads

REPO_URL="https://github.com/RIKEN-LQCD/qws.git"
REPO_DIR="qws"
BRANCH="${QWS_BRANCH:-master}"
SOURCE_COMMIT="${QWS_SOURCE_COMMIT:-}"
qws_case0_args=(32 6 4 3 1 1 1 1 -1 -1 6 50)
qws_case1_args=(32 6 4 3 1 1 1 2 -1 -1 6 50)
qws_case7_args=(32 6 4 3 1 2 2 2 -1 -1 6 50)

source "${PWD}/scripts/bk_functions.sh"
source "${PWD}/programs/qws/parse_timing.sh"
qws_profiler_tool=$(bk_resolve_profiler_tool fapp QWS_PROFILER_TOOL)
qws_profiler_level=$(bk_resolve_profiler_level detailed QWS_PROFILER_LEVEL)
# Section and overlap estimates require reviewed application timing data;
# they cannot be inferred by dividing the solver FOM.

mkdir -p results && : > results/result

# print_results: extract FOM from the benchmark output and append a result line.
print_results() {
    local outfile=$1
    local exp=$2
    local np=$3
    ./check.sh "$outfile" "data/$exp"
    local fom
    fom=$(qws_extract_fom_from_log "$outfile")
    bk_emit_result --from-log "$outfile" --timing-parser qws_observe_timing --timing-producer qws \
        --fom "$fom" --fom-unit s --fom-version DDSolverJacobi --exp "$exp" --nodes "$nodes" --numproc-node "$np" --nthreads "$nthreads"
}

bk_fetch_recorded_source "${REPO_URL}" "${REPO_DIR}" "${BRANCH}" "${SOURCE_COMMIT}"

if [[ -f artifacts/main ]]; then
    cp artifacts/main "${REPO_DIR}"
else
    echo "ERROR: artifacts/main not found"
    exit 1
fi

cd "${REPO_DIR}"

case "$system" in
    Flow2_Type1|Flow2_Type2)
        if [[ "$nodes" != 1 || "$numproc_node" != 1 ]]; then
            echo "qws: Flow2 CASE0 requires one node and one MPI rank" >&2
            exit 1
        fi
        module purge
        if [[ "$system" = Flow2_Type1 ]]; then
            module load oneapi/2026.1.0 impi/2021.18
            qws_mpi_opts=()
        else
            module load nvhpc/26.5 nv-hpcx/26.5
            qws_mpi_opts=(--bind-to core --map-by "ppr:1:node:PE=${nthreads}")
        fi
        export OMP_PLACES=cores
        export OMP_PROC_BIND=close
        bk_run --log CASE0 --parameter-input --launcher mpirun -n 1 "${qws_mpi_opts[@]}" -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    Fugaku|FugakuCN)
        case "$nodes" in
            1)
                bk_run --log CASE0 --parameter-input --launcher mpiexec -n 1 -- ./main "${qws_case0_args[@]}"
                print_results CASE0 CASE0 1 >> ../results/result
                bk_run --log CASE1 --parameter-input --launcher mpiexec -n 2 -- ./main "${qws_case1_args[@]}"
                print_results CASE1 CASE1 2 >> ../results/result
                if bk_profiler_enabled "$qws_profiler_tool"; then
                    bk_profile --from-log CASE0 -- bk_capture_profile "$qws_profiler_tool" "$qws_profiler_level" -- mpiexec -n 1 ./main "${qws_case0_args[@]}"
                fi
                ;;
            2)
                bk_run --log CASE7 --parameter-input --launcher mpiexec -n 8 -- ./main "${qws_case7_args[@]}"
                print_results CASE7 CASE7 4 >> ../results/result
                if bk_profiler_enabled "$qws_profiler_tool"; then
                    bk_profile --from-log CASE7 -- bk_capture_profile "$qws_profiler_tool" "$qws_profiler_level" -- mpiexec -n 8 ./main "${qws_case7_args[@]}"
                fi
                ;;
            *)
                echo "Undefined node numbers for system: $system"
                exit 1
                ;;
        esac
        ;;
    RIKYU)
        module load nvhpc-hpcx/26.3
        export OMP_NUM_THREADS="$nthreads"
        export OMP_PLACES=cores
        export OMP_PROC_BIND=close
        bk_run --log CASE0 --parameter-input --launcher mpirun --bind-to none -n 1 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    RC_GH200)
        module load system/qc-gh200 nvhpc-hpcx/25.9
        bk_run --log CASE0 --parameter-input --launcher mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=72 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    RC_GENOA)
        module load system/genoa mpi/openmpi-x86_64
        bk_run --log CASE0 --parameter-input --launcher mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=96 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    RC_DGXSP)
        source /etc/profile.d/modules.sh
        module load system/ng-dgx nvhpc-hpcx/26.3
        bk_run --log CASE0 --parameter-input --launcher mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=20 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    RC_FX700)
        module load system/fx700 FJSVstclanga
        bk_run --log CASE0 --parameter-input --launcher mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=12 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    MiyabiG)
        module purge
        module load nvidia/26.3 nv-hpcx/26.3
        bk_run --log CASE0 --parameter-input --launcher mpirun -n 1 --bind-to core --map-by ppr:1:node:PE=72 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    MiyabiC)
        bk_run --log CASE0 --parameter-input --launcher mpirun -n 1 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    GenkaiA|GenkaiB|GenkaiC)
        qws_numproc=$((nodes * numproc_node))
        module load intel/2023.2 mvapich/3.0-intel2023.2
        bk_run --log CASE0 --parameter-input --launcher mpirun -n ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    Grand_C|Grand_G)
        qws_numproc=$((nodes * numproc_node))
        module load intel impi
        if [[ -n "${I_MPI_ROOT:-}" && -d "${I_MPI_ROOT}/bin" ]]; then
            export PATH="${I_MPI_ROOT}/bin:${PATH}"
        fi
        qws_mpi_launcher=$(command -v mpirun || command -v mpiexec || command -v mpiexec.hydra || true)
        if [[ -z "$qws_mpi_launcher" ]]; then
            echo "qws: mpirun/mpiexec/mpiexec.hydra not found after module load intel impi" >&2
            echo "qws: PATH=${PATH}" >&2
            echo "qws: MPI launcher candidates:" >&2
            type -a mpirun mpiexec mpiexec.hydra mpiicc mpiicpc mpiicpx 2>&1 >&2 || true
            echo "qws: loaded modules:" >&2
            module list >&2 || true
            exit 1
        fi
        bk_run --log CASE0 --parameter-input --launcher "$qws_mpi_launcher" -n ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    AOBA_A|AOBA_B|AOBA_S)
        qws_numproc=$((nodes * numproc_node))
        bk_run --log CASE0 --parameter-input --launcher mpirun -np ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    SQUID_CPU)
        qws_numproc=$((nodes * numproc_node))
        qws_mpi_opts=()
        if [[ -n "${NQSII_MPIOPTS:-}" ]]; then
            read -r -a qws_mpi_opts <<< "${NQSII_MPIOPTS}"
        fi
        module load BaseCPU
        export OMP_NUM_THREADS="${nthreads}"
        bk_run --log CASE0 --parameter-input --launcher mpirun "${qws_mpi_opts[@]}" -np ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    SQUID_GPU)
        qws_numproc=$((nodes * numproc_node))
        qws_mpi_opts=()
        if [[ -n "${NQSII_MPIOPTS:-}" ]]; then
            read -r -a qws_mpi_opts <<< "${NQSII_MPIOPTS}"
        fi
        module load BaseGPU
        export OMP_NUM_THREADS="${nthreads}"
        bk_run --log CASE0 --parameter-input --launcher mpirun "${qws_mpi_opts[@]}" -np ${qws_numproc} --bind-to none -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    SQUID_VECTOR)
        qws_numproc=$((nodes * numproc_node))
        qws_mpi_opts=()
        if [[ -n "${NQSII_MPIOPTS:-}" ]]; then
            read -r -a qws_mpi_opts <<< "${NQSII_MPIOPTS}"
        fi
        module load BaseVEC
        export OMP_NUM_THREADS="${nthreads}"
        bk_run --log CASE0 --parameter-input --launcher mpirun "${qws_mpi_opts[@]}" -np ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    Odyssey)
        if [[ -r /etc/profile.d/modules.sh ]]; then
            source /etc/profile.d/modules.sh
        else
            echo "qws: /etc/profile.d/modules.sh is not readable" >&2
        fi
        module unload fjmpi fj odyssey 2>/dev/null || true
        module load odyssey fj fjmpi
        export OMP_NUM_THREADS=12
        export PLE_MPI_STD_EMPTYFILE=off
        bk_run --log CASE0 --parameter-input --launcher mpiexec -n 1 -ofout stdout.1.0 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    Aquarius)
        module purge
        module load intel
        source /work/opt/local/x86_64/cores/intel/2023.0.0/mpi/latest/env/vars.sh
        export OMP_NUM_THREADS=8
        export I_MPI_PIN=1
        bk_run --log CASE0 --parameter-input --launcher mpiexec -n 1 -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    Pegasus)
        qws_numproc=$((nodes * numproc_node))
        module load intel/2025.3.1 intmpi/2025.3.1
        bk_run --log CASE0 --parameter-input --launcher mpirun -n ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    Sirius)
        qws_numproc=$((nodes * numproc_node))
        module load aocc/5.0.0 openmpi/5.0.10/aocc5.0.0
        bk_run --log CASE0 --parameter-input --launcher mpirun -n ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    TSUBAME4)
        qws_numproc=$((nodes * numproc_node))
        module load openmpi/5.0.10-gcc aocc/4.1.0
        export OMPI_CC=clang OMPI_CXX=clang++ OMPI_FC=flang
        bk_run --log CASE0 --parameter-input --launcher mpirun -n ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    OCTOPUS)
        qws_numproc=$((nodes * numproc_node))
        module load BaseCPU inteloneAPI
        export OMP_NUM_THREADS="${nthreads}"
        export OMP_PROC_BIND=close
        export OMP_PLACES=cores
        bk_run --log CASE0 --parameter-input --launcher mpirun -n ${qws_numproc} -- ./main "${qws_case0_args[@]}"
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    Camphor3)
        camphor3_modulepath="${MODULEPATH:-}"
        if [[ -r /etc/profile.d/modules.sh ]]; then
            source /etc/profile.d/modules.sh
        elif [[ -r /etc/profile.d/z00_lmod.sh ]]; then
            source /etc/profile.d/z00_lmod.sh
        else
            echo "qws: no module init script found" >&2
        fi
        if [[ -n "${MODULEPATH:-}" ]]; then
            camphor3_modulepath="${MODULEPATH}"
        fi
        module purge
        if [[ -n "${camphor3_modulepath:-}" ]]; then
            export MODULEPATH="${camphor3_modulepath}"
        fi
        module load intel/2023.2 intelmpi/2023.2 PrgEnvIntel/2023
        export OMP_NUM_THREADS="${nthreads}"
        export I_MPI_PIN=1
        if [[ "${SLURM_CONF:-}" == /etc/slurm/sysA/* ]]; then
            unset SLURM_CONF
        fi
        bk_run --log CASE0 --parameter-input --launcher srun -n 1 -c "${nthreads}" -- ./main "${qws_case0_args[@]}"
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
