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
INPUT_ARCHIVE_DEFAULT="/vol0003/rccs-sdt/data/a01010/benchmark_data/SALMON.tar.gz"
INPUT_ARCHIVE_CLOUD="/lvs0/dne1/rccs-nghpcadu/CX_input/SALMON/SALMON.tar.gz"
INPUT_ARCHIVE_RIKYU="/data1/rkp00012/CX_input/SALMON/SALMON.tar.gz"
AOCL_ROOT_DEFAULT="/lvs0/rccs-nghpcadu/nakamura/aocl/install"

mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"

if [[ ! -x artifacts/salmon ]]; then
  echo "Required artifact not found or not executable: artifacts/salmon" >&2
  exit 1
fi

case "${system}" in
  Fugaku)
    input_archive="${INPUT_ARCHIVE_DEFAULT}"
    exec_gs=(-stdin Si-1-1-1.nml ./salmon)
    exec_rt=(-stdin Si-1-1-1-tddft.nml ./salmon)
    ;;
  RIKYU)
    input_archive="${BK_SALMON_INPUT_ARCHIVE:-${INPUT_ARCHIVE_RIKYU}}"
    exec_gs=(./salmon)
    exec_rt=(./salmon)
    ;;
  RC_GH200|RC_DGXSP|RC_GENOA)
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
cd "${WORK_DIR}"

case "${system}" in
  Fugaku)
    export OMP_NUM_THREADS="${nthreads}"
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
    module load nvhpc/26.3
    export OMP_NUM_THREADS="${nthreads}"
    for nml in Si-1-1-1.nml Si-1-1-1-tddft.nml; do
      awk -v nproc_ob="${n_ranks}" '
        /^&parallel$/ { print; print "  nproc_ob = " nproc_ob; print "  nproc_k = 1"; print "  nproc_rgrid = 1, 1, 1"; in_parallel=1; next }
        in_parallel && /^\// { in_parallel=0; print; next }
        in_parallel { next }
        { print }
      ' "$nml" > "$nml.tmp" && mv "$nml.tmp" "$nml"
    done
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
      export UCX_IB_GPU_DIRECT_RDMA=no
    fi
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
  local logfile="$1"
  shift
  case "${system}" in
    RIKYU)
      if [[ "${n_ranks}" -gt 1 ]]; then
        mpirun -n "${n_ranks}" ./wrapper.sh "$@" > "${logfile}" 2>&1
      else
        mpirun -n "${n_ranks}" "$@" > "${logfile}" 2>&1
      fi
      ;;
    RC_GENOA)
      mpirun -n "${n_ranks}" --bind-to core --map-by "ppr:${numproc_node}:node:PE=${nthreads}" "$@" > "${logfile}" 2>&1
      ;;
    *)
      mpiexec -n "${n_ranks}" "$@" > "${logfile}" 2>&1
      ;;
  esac
}

run_salmon_or_diagnose() {
  local stage="$1"
  local marker_file="$2"
  local logfile="$3"
  shift 3

  if run_salmon "${logfile}" "$@"; then
    return 0
  fi

  echo "SALMON ${stage} run failed" >&2
  echo "---- ${logfile} tail ----" >&2
  tail -n 80 "${logfile}" >&2 || true
  echo "---- files updated since ${stage} start ----" >&2
  print_salmon_output_diagnostics "${marker_file}"
  exit 1
}

salmon_output_has_marker_since() {
  local logfile="$1"
  local marker_file="$2"
  local success_pattern='total[[:space:]]+calculation[[:space:]]+time|total[[:space:]]+.*elapsed[[:space:]]+time|elapsed[[:space:]]+time'

  if grep -Eiq "${success_pattern}" "${logfile}"; then
    return 0
  fi

  while IFS= read -r -d '' output_file; do
    if grep -Eiq "${success_pattern}" "${output_file}"; then
      return 0
    fi
  done < <(find . -type f -newer "${marker_file}" ! -path "./input/*" -print0)

  return 1
}

print_salmon_output_diagnostics() {
  local marker_file="$1"
  local output_file

  find . -maxdepth 4 -type f -newer "${marker_file}" ! -path "./input/*" -printf '%p\n' \
    | sort \
    | sed -n '1,120p' >&2

  while IFS= read -r -d '' output_file; do
    echo "---- ${output_file} tail ----" >&2
    tail -n 20 "${output_file}" >&2 || true
  done < <(
    find . -maxdepth 5 -type f -newer "${marker_file}" \
      \( -name 'stdout*' -o -name 'stderr*' -o -name '*.log' \) \
      ! -path "./input/*" -print0 \
      | sort -z
  )
}

touch .gs_start_marker
gs_start=$(date +%s.%N)
if uses_stdin_input "${system}"; then
  run_salmon_or_diagnose GS .gs_start_marker gs.log "${exec_gs[@]}" < Si-1-1-1.nml
else
  run_salmon_or_diagnose GS .gs_start_marker gs.log "${exec_gs[@]}"
fi
gs_end=$(date +%s.%N)

if [[ -d data_for_restart ]]; then
  rm -rf restart
  mv data_for_restart restart
fi

touch .rt_start_marker
rt_start=$(date +%s.%N)
if uses_stdin_input "${system}"; then
  run_salmon_or_diagnose RT .rt_start_marker rt.log "${exec_rt[@]}" < Si-1-1-1-tddft.nml
else
  run_salmon_or_diagnose RT .rt_start_marker rt.log "${exec_rt[@]}"
fi
rt_end=$(date +%s.%N)

gs_elapsed=$(awk -v start="${gs_start}" -v end="${gs_end}" 'BEGIN {printf "%.6f", end - start}')
rt_elapsed=$(awk -v start="${rt_start}" -v end="${rt_end}" 'BEGIN {printf "%.6f", end - start}')
total_elapsed=$(awk -v gs="${gs_elapsed}" -v rt="${rt_elapsed}" 'BEGIN {printf "%.6f", gs + rt}')

cp gs.log rt.log "${RESULTS_DIR}/"

if ! salmon_output_has_marker_since gs.log .gs_start_marker || ! salmon_output_has_marker_since rt.log .rt_start_marker; then
  echo "SALMON success marker not found in both gs.log and rt.log" >&2
  echo "---- gs.log tail ----" >&2
  tail -n 40 gs.log >&2 || true
  echo "---- rt.log tail ----" >&2
  tail -n 40 rt.log >&2 || true
  echo "---- files updated since GS start ----" >&2
  print_salmon_output_diagnostics .gs_start_marker
  echo "---- files updated since RT start ----" >&2
  print_salmon_output_diagnostics .rt_start_marker
  exit 1
fi

{
  bk_emit_result \
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
