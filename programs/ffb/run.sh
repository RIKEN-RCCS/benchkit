#!/bin/bash
set -euo pipefail

system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
n_ranks=$((nodes * numproc_node))

source "${PWD}/scripts/bk_functions.sh"

INPUT_ARCHIVE_CPU="/vol0003/rccs-sdt/data/a01008/apps/ffb/benchmark-input.tar.gz"
INPUT_ARCHIVE_GPU="/lvs0/rccs-sdt/kazuto.ando/apps/ffb/benchmark-input.tar.gz"
WORK_DIR="ffb_run"
RESULTS_DIR="${PWD}/results"

mkdir -p "${RESULTS_DIR}"
: > "${RESULTS_DIR}/result"

if [[ ! -f artifacts/les3x.mpi ]]; then
  echo "Required artifact not found: artifacts/les3x.mpi" >&2
  exit 1
fi

rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"
cp artifacts/les3x.mpi "${WORK_DIR}/"

case "$system" in
  FugakuCN)
    input_archive="${INPUT_ARCHIVE_CPU}"
    ;;
  RC_GH200)
    input_archive="${INPUT_ARCHIVE_GPU}"
    ;;
  *)
    echo "Unknown Running system: $system" >&2
    exit 1
    ;;
esac

if [[ ! -f "$input_archive" ]]; then
  echo "Input archive not found: $input_archive" >&2
  exit 1
fi

tar -xzf "$input_archive" --strip-components=1 -C "${WORK_DIR}"
cd "${WORK_DIR}"

if [[ ! -x ./les3x.mpi ]]; then
  chmod +x ./les3x.mpi
fi

case "$system" in
  FugakuCN)
    export OMP_NUM_THREADS="${nthreads}"
    bk_run --log les3x.stdout.log -- mpiexec -n "${n_ranks}" ./les3x.mpi

    if grep -q 'USRT:TIME-LOOP' les3x.stdout.log; then
      cp les3x.stdout.log les3x.log.P0001
      sed -i -e "s/D+/E+/g" -e "s/D-/E-/g" les3x.log.P*
    fi
    ;;
  RC_GH200)
    module purge
    module load system/qc-gh200 nvhpc/24.3
    bk_run --log les3x.stdout.log -- mpiexec -np "${n_ranks}" ./les3x.mpi
    ;;
esac

if [[ ! -f les3x.log.P0001 ]]; then
  echo "FFB log file not found: les3x.log.P0001" >&2
  exit 1
fi

fom=$(awk '/^[[:space:]]*1[[:space:]]+USRT:TIME-LOOP[[:space:]]+/ {print $3; exit}' les3x.log.P0001)
if [[ -z "${fom:-}" ]]; then
  echo "Failed to extract FOM from les3x.log.P0001" >&2
  exit 1
fi

if ! awk -v fom="$fom" 'BEGIN { exit !(fom <= 100) }'; then
  echo "FFB validation failed: FOM must be <= 100, got $fom" >&2
  exit 1
fi

bk_emit_result \
  --from-log les3x.stdout.log \
  --fom "$fom" \
  --fom-unit s \
  --fom-version "67.01" \
  --exp "cavity" \
  --nodes "$nodes" \
  --numproc-node "$numproc_node" \
  --nthreads "$nthreads" >> "${RESULTS_DIR}/result"
