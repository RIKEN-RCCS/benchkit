#!/bin/bash
set -euo pipefail

system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
n_ranks=$((nodes * numproc_node))

source scripts/bk_functions.sh

# FOM.awk ships next to this script and BenchKit invokes run.sh from the
# repo root, so anchor it to the script's own location -- same reason
# build.sh anchors src/GMRES-PETSc.cpp.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARTIFACT="${PWD}/artifacts/GMRES-PETSc"
RESULTS_DIR="${PWD}/results"
mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"

if [[ ! -x "${ARTIFACT}" ]]; then
  echo "Required artifact not found or not executable: ${ARTIFACT}" >&2
  exit 1
fi

export OMP_NUM_THREADS="${nthreads}"

# The benchmark matrix (stokes2, 4,260,568 x 4,260,568, 256,285,536 nnz --
# a Stokes flow saddle-point system from an ellipsoid mesh, generated via
# Gmsh/FreeFEM and written directly to PETSc binary format by FreeFEM's
# ObjectView, so no mtx2petsc conversion is needed) is pre-staged at a
# fixed path per system. See README.md for how each copy was produced and
# how to re-stage it.
logfile="solve.log"
# PETSc's own event log, parsed by FOM.awk for the per-routine breakdown.
logpetsc="petsc.log"

# GMRES restart (Krylov subspace size). PETSc's default of 30 is too small for
# these Stokes systems: stokes3/stokes4 stagnate at it and never converge.
# 100 converges stokes2 at every rank count and stokes3 at 2 and 4 GPUs. The
# operators are singular, so no restart guarantees convergence and larger is
# not monotonically better -- 80 converged and then broke down on a rerun of
# the same config.
KSP_RESTART="${BK_PETSC_GMRES_RESTART:-100}"
case "${system}" in
  RIKYU) DATA="${BK_PETSC_GMRES_MATRIX:-/data1/rkp00015/CX_input/petsc-gmres/stokes2.dat}" ;;
  Fugaku) DATA="${BK_PETSC_GMRES_MATRIX:-/vol0500/share/ra250029/CX_input/petsc-gmres/stokes2.dat}" ;;
  RC_DGXSP) DATA="${BK_PETSC_GMRES_MATRIX:-/lvs0/rccs-nghpcadu/CX_input/petsc-gmres/stokes2.dat}" ;;
  *) echo "Unknown system: ${system}" >&2; exit 1 ;;
esac

matrix_name="$(basename "${DATA}" .dat)"
bk_record_input \
  --file "${DATA}" --expected-manifest "${APP_DIR}/input-manifest.json" \
  --dataset-id petsc-gmres-stokes2 \
  --type matrix \
  --result-exp "${matrix_name}" \
  --parameter ksp_gmres_restart "${KSP_RESTART}" \
  --recipe "Stokes flow saddle-point matrix generated with Gmsh/FreeFEM and stored in PETSc binary format."

case "${system}" in
  RIKYU)
    module load nvhpc-hpcx/26.3
    # One MPI rank per GPU: each rank gets a distinct GPU via
    # CUDA_VISIBLE_DEVICES (set inside mpirun so OMPI_COMM_WORLD_LOCAL_RANK
    # is available per-rank), and -mat_type aijcusparse puts the matrix
    # on-device. Without these the solve runs on CPU even though GPUs
    # are allocated.
    bk_run --log "${logfile}" -- mpirun -np "${n_ranks}" -N "${numproc_node}" --bind-to core --map-by core \
      bash -c 'export CUDA_VISIBLE_DEVICES=$OMPI_COMM_WORLD_LOCAL_RANK; exec "$@"' \
      _ "${ARTIFACT}" -f "${DATA}" -pc_type gamg -pc_gamg_square_graph 0 \
      -mat_type aijcusparse -matload_block_size 1 \
      -ksp_gmres_restart "${KSP_RESTART}" \
      -log_view ":${logpetsc}" -log_view_gpu_time
    ;;
  Fugaku)
    # /vol0002 is at quota (0 byte hard limit -- true for every group
    # tried), but /vol0005 isn't; this repo's FJ queue.csv template
    # already declares GFSCACHE for both (and /vol0003, /vol0004), so no
    # extra -x PJM_LLIO_GFSCACHE handling is needed here.
    # /vol0500 (not /vol0005 -- the "resolved" path fs_mkdir reported when
    # this was staged) is what actually resolves from a compute-node job;
    # found by testing the real run.sh in a real job, not by trusting the
    # canonical-looking path a filesystem tool reported.
    module load lang/tcsds-1.2.43
    module load LLVM/llvmorg-22.1.0
    bk_run --log "${logfile}" -- mpiexec -n "${n_ranks}" \
      "${ARTIFACT}" -f "${DATA}" -pc_type gamg -pc_gamg_square_graph 0 \
      -matload_block_size 1 \
      -ksp_gmres_restart "${KSP_RESTART}" \
      -log_view ":${logpetsc}"
    ;;
  RC_DGXSP)
    # GPU run (1 rank/GPU) -- see build.sh. /lvs0 group storage IS mounted
    # and readable on the ng-dgx compute nodes (verified with a compute-node
    # read test), so the data lives in the site's CX_input like everywhere
    # else.
    source /etc/profile.d/modules.sh
    module load system/ng-dgx nvhpc-hpcx
    bk_run --log "${logfile}" -- mpirun -np "${n_ranks}" \
      bash -c 'export CUDA_VISIBLE_DEVICES=$OMPI_COMM_WORLD_LOCAL_RANK; exec "$@"' \
      _ "${ARTIFACT}" -f "${DATA}" -pc_type gamg -pc_gamg_square_graph 0 \
      -mat_type aijcusparse -matload_block_size 1 \
      -ksp_gmres_restart "${KSP_RESTART}" \
      -log_view ":${logpetsc}" -log_view_gpu_time
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

if ! grep -q "^FOM: ranks=" "${logfile}" 2>/dev/null; then
  echo "petsc-gmres success marker not found" >&2
  bk_diagnose_log "${logfile}"
  exit 1
fi

ksp_iter_time=$(grep "^FOM: ranks=" "${logfile}" | sed -E 's/.*ksp_iter_time_s=([0-9.]+).*/\1/')

# bk_emit_result must come BEFORE the SECTION lines: scripts/result.sh
# attaches sections to the FOM block currently open and resets them on each
# FOM line, so sections emitted first are silently dropped from the Result
# JSON while result.sh still exits 0.
bk_emit_result \
  --from-log "${logfile}" \
  --fom "${ksp_iter_time}" \
  --fom-unit s \
  --fom-version ksp_iter_time \
  --exp "${matrix_name}" \
  --nodes "${nodes}" \
  --numproc-node "${numproc_node}" \
  --nthreads "${nthreads}" >> "${RESULTS_DIR}/result"

# Per-routine breakdown behind the FOM: MatMult and KSPSolve time, flop and
# flop/s, plus the SF pack+unpack time that stands for halo-exchange cost.
# Kept as a collected artifact and mirrored into SECTION lines, the only
# structured channel BenchKit has for sub-timings.
if [[ -f "${logpetsc}" ]]; then
  awk -f "${APP_DIR}/FOM.awk" "${logpetsc}" > "${RESULTS_DIR}/fom_details.txt"
  cat "${RESULTS_DIR}/fom_details.txt"
  # A time reads "n/a" when -log_view could not attribute wall time to the
  # event. bk_emit_section rejects a non-numeric time, which under set -e
  # would abort the run and report failure for an otherwise good result --
  # warn and skip instead.
  awk -f "${APP_DIR}/FOM.awk" "${logpetsc}" | awk '
    function num(v) { return v ~ /^[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$/ }
    $1 == "MatMult"       { print (num($2) ? "MatMult "         $2 : "!MatMult") }
    $1 == "KSPSolve"      { print (num($2) ? "KSPSolve "        $2 : "!KSPSolve") }
    $1 == "SFPack/Unpack" { print (num($2) ? "SFPack_SFUnpack " $2 : "!SFPack_SFUnpack") }' |
  while read -r _sec _time; do
    if [[ "${_sec}" == !* ]]; then
      echo "warning: no numeric time for ${_sec#!} in ${logpetsc}, section not emitted" >&2
      continue
    fi
    bk_emit_section "${_sec}" "${_time}" "" "results/fom_details.txt" \
      >> "${RESULTS_DIR}/result"
  done
else
  echo "warning: ${logpetsc} not produced, skipping FOM detail breakdown" >&2
fi
