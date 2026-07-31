#!/bin/bash
set -euo pipefail

system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
n_ranks=$((nodes * numproc_node))

source scripts/bk_functions.sh

RESULTS_DIR="${PWD}/results"
RUN_DIR="${PWD}/sbd_run"
INPUT_DIR="${BK_SBD_INPUT_DIR:-${PWD}/programs/sbd/data/h2o}"

mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"

case "${system}" in
  RIKYU)
    module purge
    module load nvhpc/26.3
    ;;
  RC_DGXSP)
    source /etc/profile.d/modules.sh
    module purge
    module load system/ng-dgx nvhpc-hpcx-cuda13/26.3
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

for input_file in fcidump.txt h2o-1em7-alpha.txt; do
  if [[ ! -f "${INPUT_DIR}/${input_file}" ]]; then
    echo "SBD input not found: ${INPUT_DIR}/${input_file}" >&2
    exit 1
  fi
done
if [[ ! -x artifacts/diag ]]; then
  echo "Required artifact not found or not executable: artifacts/diag" >&2
  exit 1
fi

rm -rf "${RUN_DIR}"
mkdir -p "${RUN_DIR}"
cp artifacts/diag "${RUN_DIR}/diag"
cp "${INPUT_DIR}/fcidump.txt" "${INPUT_DIR}/h2o-1em7-alpha.txt" "${RUN_DIR}/"
cd "${RUN_DIR}"
export OMP_NUM_THREADS="${nthreads}"

mpirun -np "${n_ranks}" bash -lc \
  'export CUDA_VISIBLE_DEVICES=$OMPI_COMM_WORLD_LOCAL_RANK; exec ./diag \
    --fcidump fcidump.txt --adetfile h2o-1em7-alpha.txt \
    --method 0 --block 10 --iteration 4 --tolerance 1.0e-8 \
    --init 0 --shuffle 0 --carryover_type 0 --rdm 0 \
    --task_comm_size 1 --adet_comm_size 2 --bdet_comm_size 2' \
  > diag.log 2>&1

davidson_time=$(grep -E 'Elapsed time for davidson ' diag.log | tail -n 1 | awk '{print $(NF-1)}')
energy=$(grep -E '^ Energy = ' diag.log | tail -n 1 | awk '{print $3}')
mult_time=$(grep -E 'Elapsed time for mult ' diag.log | tail -n 1 | awk '{print $(NF-1)}')

if [[ -z "${davidson_time}" || -z "${energy}" ]]; then
  echo "SBD completion markers not found" >&2
  tail -n 80 diag.log >&2
  exit 1
fi

cp diag.log "${RESULTS_DIR}/"
bk_emit_result --fom "${davidson_time}" --fom-unit s \
  --fom-version "davidson_internal_s" --exp "H2O-1em7" \
  --nodes "${nodes}" --numproc-node "${numproc_node}" \
  --nthreads "${nthreads}" >> "${RESULTS_DIR}/result"
if [[ -n "${mult_time}" ]]; then
  bk_emit_section mult "${mult_time}" >> "${RESULTS_DIR}/result"
fi
printf 'SBD energy: %s\n' "${energy}" >&2
