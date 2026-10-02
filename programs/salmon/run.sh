#!/bin/bash
set -euo pipefail

system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
n_ranks=$((nodes * numproc_node))

source "${PWD}/scripts/bk_functions.sh"

RESULTS_DIR="${PWD}/results"
WORK_DIR="${PWD}/salmon_run"
INPUT_ARCHIVE_CLOUD="/lvs0/rccs-nghpcadu/CX_input/SALMON/SALMON.tar.gz"
AOCL_ROOT_DEFAULT="/lvs0/rccs-nghpcadu/nakamura/aocl/install"

# Pre-staged folded restarts. The ground state is computed once offline and
# folded to a complex Gamma-point TDDFT restart (see README.md), then stored
# on each machine, so the benchmark runs TDDFT only and never pays for a
# from-scratch ground state. Add a new case here (and a
# matching directory on that system) to move another system onto this
# path -- see the RIKYU or RC_DGXSP entries for the shape a new one needs
# (restart/, *.psp8, and one TDDFT .nml, all siblings in one directory).
RIKYU_RESTART_DIR_DEFAULT="/data1/rkp00015/CX_input/SALMON/3x3x3-folded"
RIKYU_RESTART_NML="Si-3-3-3-tddft.nml"
RC_DGXSP_RESTART_DIR_DEFAULT="/lvs0/rccs-nghpcadu/CX_input/SALMON_2x2x2_folded"
RC_DGXSP_RESTART_NML="Si-2-2-2-tddft.nml"
FUGAKU_RESTART_DIR_DEFAULT="/vol0500/share/ra250029/CX_input/SALMON/3x3x3-folded"
FUGAKU_RESTART_NML="Si-3-3-3-tddft.nml"
# RIKYU and Fugaku carry *different* 3x3x3 folds (same size, distinct
# provenance: wfn.bin SHA-256 d2f884a7... vs 720a8778...), so those two
# systems' results are not expected to be bitwise identical.
# Fugaku's list.csv row MUST use enough MPI ranks that each rank's local
# wfn.bin chunk stays under ~2GB: SALMON's default restart reader
# (method_wf_distributor='single') does one MPI_File_read_all per rank
# spanning its whole orbital slice, and Fujitsu MPI's MPI-IO throws
# MPI_ERR_ARG on per-rank reads above that size (a real, reproduced,
# vendor-specific MPI-IO limit -- confirmed independent of both restart
# provenance and physical memory: it reproduced identically whether the
# restart was folded on the login node or a genuine A64FX compute node,
# and separately from the plain OOM that a too-small node count/rank
# count hits first for this restart's 37GB wfn.bin). 24 ranks (81
# orbitals/rank, ~1.5GB/rank) is the smallest node count validated so far
# for the 3x3x3 case; going lower reintroduces the failure.

mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"

if [[ ! -x artifacts/salmon ]]; then
  echo "Required artifact not found or not executable: artifacts/salmon" >&2
  exit 1
fi

uses_prestaged_restart() {
  case "$1" in
    RIKYU|RC_DGXSP|Fugaku)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

uses_stdin_input() {
  case "$1" in
    RIKYU|RC_GH200|RC_DGXSP|RC_GENOA)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

if uses_prestaged_restart "${system}"; then
  case "${system}" in
    RIKYU)
      restart_dir="${BK_SALMON_RESTART_DIR:-${RIKYU_RESTART_DIR_DEFAULT}}"
      tddft_nml="${RIKYU_RESTART_NML}"
      ;;
    RC_DGXSP)
      restart_dir="${BK_SALMON_RESTART_DIR:-${RC_DGXSP_RESTART_DIR_DEFAULT}}"
      tddft_nml="${RC_DGXSP_RESTART_NML}"
      ;;
    Fugaku)
      restart_dir="${BK_SALMON_RESTART_DIR:-${FUGAKU_RESTART_DIR_DEFAULT}}"
      tddft_nml="${FUGAKU_RESTART_NML}"
      ;;
  esac

  if [[ ! -d "${restart_dir}" || ! -d "${restart_dir}/restart" ]]; then
    echo "Pre-staged restart not found: ${restart_dir} (expects restart/, *.psp8, ${tddft_nml})" >&2
    exit 1
  fi

  bk_record_input --directory "${restart_dir}" --type restart \
    --dataset-id salmon-folded-restart \
    --parameter input_set "${tddft_nml}" \
    --recipe "Offline ground-state data folded to a complex Gamma-point TDDFT restart; the run consumes the restart, pseudopotentials, and TDDFT input."

  cp artifacts/salmon "${WORK_DIR}/salmon"
  chmod +x "${WORK_DIR}/salmon"
  cp "${restart_dir}/${tddft_nml}" "${restart_dir}"/*.psp8 "${WORK_DIR}/"
  # Symlink, never copy: the restart is O(10s of GB) (a folded 3x3x3
  # wfn.bin alone is ~35GB) and is immutable input, so copying it into a
  # throwaway per-run work dir would burn most of the wall-clock budget on
  # I/O instead of the benchmark itself.
  ln -s "${restart_dir}/restart" "${WORK_DIR}/restart"
  grep -Ein '^[[:space:]]*theory[[:space:]]*=' "${WORK_DIR}/${tddft_nml}" >&2 || true
else
  case "${system}" in
    RC_GH200|RC_GENOA)
      input_archive="${INPUT_ARCHIVE_CLOUD}"
      exec_gs=(./salmon)
      exec_rt=(./salmon)
      ;;
    *)
      echo "Unknown system: ${system}" >&2
      exit 1
      ;;
  esac

  if [[ ! -f "${input_archive}" ]]; then
    echo "Input archive not found: ${input_archive}" >&2
    exit 1
  fi

  bk_record_input --file "${input_archive}" --type archive \
    --dataset-id salmon-si-1x1x1-archive \
    --parameter input_set "Si-1-1-1 GS/RT inputs" \
    --recipe "Archive containing SALMON ground-state and TDDFT input files; the run generates the restart consumed by TDDFT."

  mkdir -p "${WORK_DIR}/input"
  tar -xzf "${input_archive}" -C "${WORK_DIR}/input"

  input_dir=$(find "${WORK_DIR}/input" -type d -path "*/Si-1-1-1/input" | head -n 1)
  if [[ -z "${input_dir}" ]]; then
    input_dir=$(find "${WORK_DIR}/input" -type f -name "Si-1-1-1.nml" -printf '%h\n' | head -n 1)
  fi
  if [[ -z "${input_dir}" || ! -d "${input_dir}" ]]; then
    echo "SALMON Si-1-1-1 input directory not found in ${input_archive}" >&2
    exit 1
  fi

  cp artifacts/salmon "${WORK_DIR}/salmon"
  chmod +x "${WORK_DIR}/salmon"
  cp "${input_dir}"/* "${WORK_DIR}/"
  grep -Ein '^[[:space:]]*theory[[:space:]]*=' "${WORK_DIR}/Si-1-1-1.nml" "${WORK_DIR}/Si-1-1-1-tddft.nml" >&2 || true
fi
cd "${WORK_DIR}"

case "${system}" in
  Fugaku)
    export OMP_NUM_THREADS="${nthreads}"
    # Fugaku always uses the pre-staged-restart path (see
    # uses_prestaged_restart above), so tddft_nml is always set here.
    awk -v nproc_ob="${n_ranks}" '
      /^&parallel$/ { print; print "  nproc_ob = " nproc_ob; print "  nproc_k = 1"; print "  nproc_rgrid = 1, 1, 1"; in_parallel=1; next }
      in_parallel && /^\// { in_parallel=0; print; next }
      in_parallel { next }
      { print }
    ' "${tddft_nml}" > "${tddft_nml}.tmp" && mv "${tddft_nml}.tmp" "${tddft_nml}"
    ;;
  RC_GH200)
    module purge
    module load system/qc-gh200 nvhpc-hpcx-cuda12/25.7
    export OMP_NUM_THREADS="${nthreads}"
    ;;
  RC_DGXSP)
    source /etc/profile.d/modules.sh
    module purge
    module load system/ng-dgx nvhpc-hpcx-cuda13/26.3
    export OMP_NUM_THREADS="${nthreads}"
    ;;
  RC_GENOA)
    module purge
    module load system/genoa mpi/openmpi-x86_64
    export SLURM_MPI_TYPE=pmix
    aocl_root="${BK_SALMON_AOCL_ROOT:-${AOCL_ROOT_DEFAULT}}"
    aocl_blis_lib="${aocl_root}/amd-blis/lib/LP64"
    aocl_flame_lib="${aocl_root}/amd-libflame/lib/LP64"
    aocl_utils_lib=""
    aocl_utils_so="$(find "${aocl_root}" -type f -name libaoclutils.so -print -quit 2>/dev/null || true)"
    aocl_cpuid_so="$(find "${aocl_root}" -type f -name libau_cpuid.so -print -quit 2>/dev/null || true)"
    if [[ -n "${aocl_utils_so}" ]]; then
      aocl_utils_lib="$(dirname "${aocl_utils_so}")"
    fi
    if [[ -f "${aocl_blis_lib}/libblis-mt.so" && -f "${aocl_flame_lib}/libflame.so" && -n "${aocl_utils_so}" && -n "${aocl_cpuid_so}" ]]; then
      export LD_LIBRARY_PATH="${aocl_utils_lib}:${aocl_flame_lib}:${aocl_blis_lib}:${LD_LIBRARY_PATH:-}"
    fi
    export OMP_NUM_THREADS="${nthreads}"
    ;;
  RIKYU)
    module purge
    module load nvhpc-hpcx-cuda13/26.5
    export OMP_NUM_THREADS="${nthreads}"
    # Layout is set per RT run below (RIKYU benchmarks two of them).
    if [[ "${n_ranks}" -gt 1 ]]; then
      cat > wrapper.sh <<'WRAPPER'
#!/bin/bash
NCUDA_GPUS=${NCUDA_GPUS:-$(nvidia-smi -L | wc -l)}
if [ "$OMPI_COMM_WORLD_LOCAL_SIZE" -gt "$NCUDA_GPUS" ]; then
  if [ "$OMPI_COMM_WORLD_LOCAL_RANK" -eq 0 ]; then
    nvidia-cuda-mps-control -d
  fi
  sleep 10
fi
export CUDA_VISIBLE_DEVICES=$((${OMPI_COMM_WORLD_LOCAL_RANK} % ${NCUDA_GPUS}))
exec "$@"
WRAPPER
      chmod +x wrapper.sh
    fi
    # UCX_IB_GPU_DIRECT_RDMA=no was needed on 26.3 to stop a multi-node
    # hang. Ablation-tested on 26.5 (4-GPU domain, 8-GPU mixed across 2
    # nodes, and 16/32 GPUs): not needed, and neither is UCX_TLS=^cma.
    ;;
  # RC_FX700)
  #   FX700 currently fails during GS initialization even with the Fujitsu
  #   topology guard patch applied. Keep this route disabled until verified.
  #   module purge
  #   module load system/fx700 FJSVstclanga
  #   export SLURM_MPI_TYPE=pmix
  #   export OMP_NUM_THREADS="${nthreads}"
  #   ;;
esac

run_salmon() {
  case "${system}" in
    RIKYU)
      # --mca fcoll individual is REQUIRED. MPI_File_read_all reads the
      # restart straight into managed memory and OMPIO's default two-phase
      # collective I/O redistributes it through cuMemcpyAsync: that
      # deadlocks whenever the nproc_rgrid product exceeds 2, and even when
      # it does not it costs 66.9s vs 41.7s on the restart read.
      if [[ "${n_ranks}" -gt 1 ]]; then
        mpirun -n "${n_ranks}" --mca fcoll individual ./wrapper.sh "$@"
      else
        mpirun -n "${n_ranks}" --mca fcoll individual "$@"
      fi
      ;;
    RC_GENOA)
      mpirun -n "${n_ranks}" --bind-to core --map-by "ppr:${numproc_node}:node:PE=${nthreads}" "$@"
      ;;
    *)
      mpiexec -n "${n_ranks}" "$@"
      ;;
  esac
}

salmon_output_completed() {
  local logfile="$1"
  local success_pattern='total[[:space:]]+calculation[[:space:]]+time|total[[:space:]]+.*elapsed[[:space:]]+time|elapsed[[:space:]]+time'
  grep -Eiq "${success_pattern}" "${logfile}"
}

if uses_prestaged_restart "${system}"; then
  # The ground state was computed offline when the restart was staged; the
  # benchmark is TDDFT-only. Rewrite the &parallel block in place.
  salmon_set_parallel () {
    awk -v nproc_ob="$1" -v rgrid="$2" -v alloc="$3" '
      /^&parallel$/ { print; print "  nproc_ob = " nproc_ob; print "  nproc_k = 1"; print "  nproc_rgrid = " rgrid; print "  process_allocation = " q alloc q; in_parallel=1; next }
      in_parallel && /^\// { in_parallel=0; print; next }
      in_parallel { next }
      { print }
    ' q="'" "${tddft_nml}" > "${tddft_nml}.tmp" && mv "${tddft_nml}.tmp" "${tddft_nml}"
  }

  # One timed RT run at the current layout, emitting one result line.
  run_rt_once () {
    local label="$1" logfile="rt_$1.log"
    if uses_stdin_input "${system}"; then
      bk_run --log "${logfile}" --input-file "${tddft_nml}" -- run_salmon ./salmon < "${tddft_nml}"
    else
      # Fugaku (Fujitsu MPI): -stdin FILE must be an mpiexec-level argument,
      # not shell redirection -- plain `< file` only feeds rank 0's stdin
      # under pjsub's mpiexec, not all ranks.
      bk_run --log "${logfile}" --input-file "${tddft_nml}" -- run_salmon -stdin "${tddft_nml}" ./salmon
    fi
    cp "${logfile}" "${RESULTS_DIR}/"
    if ! salmon_output_completed "${logfile}"; then
      echo "SALMON RT run failed (${label})" >&2
      bk_diagnose_log "${logfile}"
      exit 1
    fi
    # FOM is SALMON's own rt-iterations timer, not wall clock: the one-time
    # restart read is ~40-150 s depending on whether Lustre is cold, which
    # swamps and reorders the comparison when two layouts run in one job.
    # Production runs do very many steps, so the RT loop is what matters.
    local rt_s
    rt_s=$(awk '/^rt iterations/ {print $(NF-3); exit}' "${logfile}")
    if [[ -z "${rt_s}" ]]; then
      echo "could not read 'rt iterations' from ${logfile}" >&2
      exit 1
    fi
    bk_emit_result \
      --from-log "${logfile}" \
      --fom "${rt_s}" \
      --fom-unit s \
      --fom-version "rt_iterations_s_folded_restart" \
      --exp "${tddft_nml%.nml}-${label}" \
      --nodes "${nodes}" \
      --numproc-node "${numproc_node}" \
      --nthreads "${nthreads}" \
      >> "${RESULTS_DIR}/result"
  }

  if [[ "${system}" == "RIKYU" && "${numproc_node}" -eq 4 ]]; then
    # Benchmark both decompositions. Orbital is currently the faster of the
    # two at every node count measured, but mixed is what a problem with less
    # orbital parallelism has to fall back on, so both are worth tracking.
    # Mixed keeps the 2x2x1 grid split inside a node (NVLink) and spreads
    # orbitals across nodes; process_allocation='grid_sequential' is required
    # for that, since the default strides icomm_r across nodes.
    salmon_set_parallel "${n_ranks}" "1, 1, 1" "orbital_sequential"
    run_rt_once orbital
    salmon_set_parallel "${nodes}"   "2, 2, 1" "grid_sequential"
    run_rt_once mixed
  else
    run_rt_once default
  fi
else
  gs_elapsed=""
  rt_elapsed=""
  if uses_stdin_input "${system}"; then
    bk_run --log gs.log --elapsed gs_elapsed -- run_salmon "${exec_gs[@]}" < Si-1-1-1.nml
  else
    bk_run --log gs.log --elapsed gs_elapsed -- run_salmon "${exec_gs[@]}"
  fi

  if [[ -d data_for_restart ]]; then
    rm -rf restart
    mv data_for_restart restart
  fi

  if uses_stdin_input "${system}"; then
    bk_run --log rt.log --elapsed rt_elapsed -- run_salmon "${exec_rt[@]}" < Si-1-1-1-tddft.nml
  else
    bk_run --log rt.log --elapsed rt_elapsed -- run_salmon "${exec_rt[@]}"
  fi
  total_elapsed=$(awk -v gs="${gs_elapsed}" -v rt="${rt_elapsed}" 'BEGIN {printf "%.6f", gs + rt}')

  cp gs.log rt.log "${RESULTS_DIR}/"

  if ! salmon_output_completed gs.log || ! salmon_output_completed rt.log; then
    echo "SALMON success marker not found in both gs.log and rt.log" >&2
    bk_diagnose_log gs.log
    bk_diagnose_log rt.log
    exit 1
  fi

  {
    bk_emit_result \
      --from-log gs.log --from-log rt.log \
      --fom "${total_elapsed}" \
      --fom-unit s \
      --fom-version "total_elapsed_time_s" \
      --exp "Si-1-1-1" \
      --nodes "${nodes}" \
      --numproc-node "${numproc_node}" \
      --nthreads "${nthreads}"
    bk_emit_section gs "${gs_elapsed}"
    bk_emit_section rt "${rt_elapsed}"
  } >> "${RESULTS_DIR}/result"
fi
