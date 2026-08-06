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
    determinant_file=h2o-1em7-alpha.txt
    experiment=H2O-1em7
    reference_energy=-76.243776776861
    energy_abs_tolerance=1.0e-12
    task_comm_size=1
    adet_comm_size=2
    bdet_comm_size=2
    ;;
  RC_DGXSP)
    source /etc/profile.d/modules.sh
    module purge
    module load system/ng-dgx nvhpc-hpcx-cuda13/26.3
    determinant_file=h2o-1em5-alpha.txt
    experiment=H2O-1em5
    reference_energy=-76.24373504205295
    energy_abs_tolerance=1.0e-12
    task_comm_size=1
    adet_comm_size=1
    bdet_comm_size=1
    ;;
  RC_GH200)
    module purge
    module load system/qc-gh200 nvhpc-hpcx-cuda13/26.3
    determinant_file=h2o-1em6-alpha.txt
    experiment=H2O-1em6
    reference_energy=-76.2437759348979
    energy_abs_tolerance=1.0e-12
    task_comm_size=1
    adet_comm_size=1
    bdet_comm_size=1
    ;;
  RC_FX700)
    module purge
    module load system/fx700 mpi/mpich-aarch64
    determinant_file=h2o-1em4-alpha.txt
    experiment=H2O-1em4
    reference_energy=-76.2429584823075
    energy_abs_tolerance=1.0e-12
    task_comm_size=1
    adet_comm_size=2
    bdet_comm_size=2
    ;;
  *)
    echo "Unknown system: ${system}" >&2
    exit 1
    ;;
esac

for input_file in fcidump.txt "${determinant_file}"; do
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
cp "${INPUT_DIR}/fcidump.txt" "${INPUT_DIR}/${determinant_file}" "${RUN_DIR}/"
cd "${RUN_DIR}"
export OMP_NUM_THREADS="${nthreads}"

diag_args=(
  --fcidump fcidump.txt
  --adetfile "${determinant_file}"
  --method 0
  --block 10
  --iteration 4
  --tolerance 1.0e-8
  --init 0
  --shuffle 0
  --carryover_type 0
  --rdm 0
  --task_comm_size "${task_comm_size}"
  --adet_comm_size "${adet_comm_size}"
  --bdet_comm_size "${bdet_comm_size}"
)

if [[ "${system}" == "RC_FX700" ]]; then
  mpirun -np "${n_ranks}" -bind-to numa ./diag "${diag_args[@]}" \
    > diag.log 2>&1
else
  mpirun -np "${n_ranks}" bash -lc \
    'export CUDA_VISIBLE_DEVICES=$OMPI_COMM_WORLD_LOCAL_RANK; exec "$@"' \
    bash ./diag "${diag_args[@]}" > diag.log 2>&1
fi

davidson_time=$(grep -E 'Elapsed time for davidson ' diag.log | tail -n 1 | awk '{print $(NF-1)}')
energy=$(grep -E '^ Energy = ' diag.log | tail -n 1 | awk '{print $3}')
mult_time=$(grep -E 'Elapsed time for mult ' diag.log | tail -n 1 | awk '{print $(NF-1)}')

if [[ -z "${davidson_time}" || -z "${energy}" ]]; then
  echo "SBD completion markers not found" >&2
  tail -n 80 diag.log >&2
  exit 1
fi
if ! awk -v actual="${energy}" -v reference="${reference_energy}" \
  -v abs_tolerance="${energy_abs_tolerance}" \
  'BEGIN {
    diff = actual - reference
    if (diff < 0) diff = -diff
    scale = reference
    if (scale < 0) scale = -scale
    exit !(diff <= abs_tolerance + 1.0e-11 * scale)
  }'; then
  echo "SBD energy mismatch: got ${energy}, expected ${reference_energy}" >&2
  exit 1
fi

cp diag.log "${RESULTS_DIR}/"
bk_emit_result --fom "${davidson_time}" --fom-unit s \
  --fom-version "davidson_internal_s" --exp "${experiment}" \
  --nodes "${nodes}" --numproc-node "${numproc_node}" \
  --nthreads "${nthreads}" >> "${RESULTS_DIR}/result"
if [[ -n "${mult_time}" ]]; then
  bk_emit_section mult "${mult_time}" >> "${RESULTS_DIR}/result"
fi
printf 'SBD energy: %s\n' "${energy}" >&2
