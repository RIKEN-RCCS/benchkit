#!/bin/bash
set -euo pipefail

system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
n_ranks=$((nodes * numproc_node))

source scripts/bk_functions.sh

ARTIFACT="${PWD}/artifacts/GMRES-PETSc"
RESULTS_DIR="${PWD}/results"
mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"

if [[ ! -x "${ARTIFACT}" ]]; then
  echo "Required artifact not found or not executable: ${ARTIFACT}" >&2
  exit 1
fi

export OMP_NUM_THREADS="${nthreads}"

# The benchmark matrix (audikw_1, SuiteSparse GHS_psdef group, 943,695 x
# 943,695, 77,651,847 nnz, converted once to PETSc binary format) is
# pre-staged at a fixed path per system rather than fetched at build/run
# time -- same convention as this repo's ffb and LQCD_dw_solver, which
# pre-stage their (much larger) source archives the same way. See
# README.md for exactly how each copy was produced and how to re-stage it.
logfile="solve.log"
touch .run_marker

case "${system}" in
  RIKYU)
    DATA=/data1/rkp00015/benchkit-data/petsc-gmres/audikw_1.petscbin
    module load nvhpc-hpcx/26.3
    mpirun -np "${n_ranks}" -N "${numproc_node}" --bind-to core --map-by core \
      "${ARTIFACT}" -f "${DATA}" -pc_type gamg -pc_gamg_square_graph 0 \
      > "${logfile}" 2>&1 || true
    ;;
  Fugaku)
    # TODO: stage audikw_1.petscbin on Fugaku group storage and fill in
    # DATA (see README.md's "Staging the data" section for the blocker
    # hit doing this -- group quota exhausted on the volumes covered by
    # this repo's own FJ queue.csv GFSCACHE declaration).
    DATA=/vol0002/data/ra000009/benchkit-data/petsc-gmres/audikw_1.petscbin
    module load lang/tcsds-1.2.43
    module load LLVM/llvmorg-22.1.0
    mpiexec -n "${n_ranks}" \
      "${ARTIFACT}" -f "${DATA}" -pc_type gamg -pc_gamg_square_graph 0 \
      > "${logfile}" 2>&1 || true
    # Fugaku's PJM mpiexec writes each rank's real stdout/stderr under
    # ./output.$PJM_JOBID/, ignoring plain shell redirection for the
    # application's own output -- fall back to searching for it if the
    # marker wasn't captured above (same pattern as this repo's sbd).
    if ! grep -q "^FOM: ranks=" "${logfile}" 2>/dev/null; then
      found=$(find . -maxdepth 5 -type f -newer .run_marker -name 'stdout*' 2>/dev/null | sort | head -n 1)
      [[ -n "${found}" ]] && logfile="${found}"
    fi
    ;;
  RC_DGXSP)
    # TODO: stage audikw_1.petscbin on R-CCS Cloud storage and fill in
    # DATA. GPU run (1 rank/GPU) -- see build.sh.
    DATA=/lustre/share/benchkit-data/petsc-gmres/audikw_1.petscbin
    source /etc/profile.d/modules.sh
    module load system/ng-dgx nvhpc-hpcx/26.3
    mpirun -np "${n_ranks}" \
      "${ARTIFACT}" -f "${DATA}" -pc_type gamg -pc_gamg_square_graph 0 \
      -mat_type aijcusparse \
      > "${logfile}" 2>&1 || true
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

if [[ ! -f "${DATA}" ]]; then
  echo "Benchmark matrix not found at ${DATA} -- see README.md for how to stage it" >&2
  exit 1
fi

if ! grep -q "^FOM: ranks=" "${logfile}" 2>/dev/null; then
  echo "petsc-gmres success marker not found" >&2
  echo "---- ${logfile} tail ----" >&2
  tail -n 80 "${logfile}" >&2 || true
  exit 1
fi

solve_time=$(grep "^FOM: ranks=" "${logfile}" | sed -E 's/.*solve_time_s=([0-9.]+).*/\1/')

bk_emit_result \
  --fom "${solve_time}" \
  --fom-unit s \
  --fom-version solve_time \
  --exp audikw_1 \
  --nodes "${nodes}" \
  --numproc-node "${numproc_node}" \
  --nthreads "${nthreads}" >> "${RESULTS_DIR}/result"
