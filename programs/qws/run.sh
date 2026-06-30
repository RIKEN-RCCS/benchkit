#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
export OMP_NUM_THREADS=$nthreads

source "${PWD}/scripts/bk_functions.sh"
qws_profiler_tool="fapp"
qws_profiler_level="detailed"
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
                mpiexec -n 1 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
                print_results output.${PJM_JOBID}/0/1/stdout.1.0 CASE0 1 >> ../results/result
                mpiexec -n 2 ./main 32 6 4 3 1 1 1 2 -1 -1 6 50 > CASE1
                print_results output.${PJM_JOBID}/0/2/stdout.2.0 CASE1 2 >> ../results/result
                if bk_profiler_enabled "$qws_profiler_tool"; then
                    bk_profiler "$qws_profiler_tool" --level "$qws_profiler_level" --archive ../results/padata0.tgz --raw-dir pa -- mpiexec -n 1 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0.profile
                else
                    emit_qws_dummy_padata ../results/padata0.tgz
                fi
                ;;
            2)
                mpiexec -n 8 ./main 32 6 4 3 1 2 2 2 -1 -1 6 50 > CASE7
                print_results output.${PJM_JOBID}/0/1/stdout.1.0 CASE7 4 >> ../results/result
                if bk_profiler_enabled "$qws_profiler_tool"; then
                    bk_profiler "$qws_profiler_tool" --level "$qws_profiler_level" --archive ../results/padata0.tgz --raw-dir pa -- mpiexec -n 8 ./main 32 6 4 3 1 2 2 2 -1 -1 6 50 > CASE7.profile
                else
                    emit_qws_dummy_padata ../results/padata0.tgz
                fi
                ;;
            *)
                echo "Undefined node numbers for system: $system"
                exit 1
                ;;
        esac
        ;;
    # FugakuLN retired; previous LN smoke run kept for reference.
    # FugakuLN)
    #     echo 'dummy call for CI test: QWS program: ./main 32 6 4 3 1 1 1 1 -1 -1 6 50'
    #     bk_emit_result --fom 123.56 --fom-version dummy --exp CheckingPrivateRepo --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
    #     emit_qws_dummy_padata ../results/padata0.tgz
    #     ;;
    RIKYU)
        module load nvhpc-hpcx/26.3
        export OMP_NUM_THREADS="$nthreads"
        export OMP_PLACES=cores
        export OMP_PROC_BIND=close
        mpirun --bind-to none -n 1 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 1 >> ../results/result
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
    GenkaiA|GenkaiB|GenkaiC)
        qws_numproc=$((nodes * numproc_node))
        module load intel/2023.2 mvapich/3.0-intel2023.2
        mpirun -n ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
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
            echo "qws: environment:" >&2
            env | sort >&2
            exit 1
        fi
        "$qws_mpi_launcher" -n ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    AOBA_A|AOBA_B|AOBA_S)
        qws_numproc=$((nodes * numproc_node))
        mpirun -np ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
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
        mpirun "${qws_mpi_opts[@]}" -np ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
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
        mpirun "${qws_mpi_opts[@]}" -np ${qws_numproc} --bind-to none ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
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
        mpirun "${qws_mpi_opts[@]}" -np ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
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
        mpiexec -n 1 -ofout CASE0 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    Aquarius)
        module purge
        module load intel
        source /work/opt/local/x86_64/cores/intel/2023.0.0/mpi/latest/env/vars.sh
        export OMP_NUM_THREADS=8
        export I_MPI_PIN=1
        mpiexec -n 1 ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 1 >> ../results/result
        ;;
    Pegasus)
        qws_numproc=$((nodes * numproc_node))
        module load intel/2025.3.1 intmpi/2025.3.1
        mpirun -n ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    Sirius)
        qws_numproc=$((nodes * numproc_node))
        module load aocc/5.0.0 openmpi/5.0.10/aocc5.0.0
        mpirun -n ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    TSUBAME4)
        qws_numproc=$((nodes * numproc_node))
        module load openmpi/5.0.10-gcc aocc/4.1.0
        export OMPI_CC=clang OMPI_CXX=clang++ OMPI_FC=flang
        mpirun -n ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
        print_results CASE0 CASE0 ${numproc_node} >> ../results/result
        ;;
    OCTOPUS)
        qws_numproc=$((nodes * numproc_node))
        module load BaseCPU inteloneAPI
        export OMP_NUM_THREADS="${nthreads}"
        export OMP_PROC_BIND=close
        export OMP_PLACES=cores
        mpirun -n ${qws_numproc} ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
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
        srun -n 1 -c "${nthreads}" ./main 32 6 4 3 1 1 1 1 -1 -1 6 50 > CASE0
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
