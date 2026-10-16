#!/bin/bash
set -euo pipefail
[[ "$(uname -m)" == aarch64 && -n "${PBS_JOBID:-}" ]] || { echo 'Native ARM PBS allocation required' >&2; exit 1; }
root=${BK_BENCHKIT_ROOT:-$PWD}
out="$root/results/sbd_type2_preflight"
module purge
module load nvhpc/26.5 nv-hpcx/26.5 cmake/4.4.3
source "$root/programs/sbd/flow2_type2_env.sh"
export OMP_NUM_THREADS=18 OMP_DYNAMIC=false OMP_PLACES=cores OMP_PROC_BIND=close
mkdir -p "$out"
module list > "$out/modules.txt" 2>&1
mpic++ -show > "$out/mpi-wrapper.txt"
g++ --version > "$out/compiler-version.txt"
cmake --version > "$out/cmake-version.txt"
cmake -S "$root/programs/sbd/cpu_preflight" -B "$out/build" \
  -DCMAKE_CXX_COMPILER=mpic++ \
  -Dnvpl_DIR="$SBD_FLOW2_NVPL_ROOT/lib/cmake/nvpl" \
  -DBLA_VENDOR=NVPL -DBLA_SIZEOF_INTEGER=4 -DBLA_THREAD=SEQ > "$out/configure.log" 2>&1
cmake --build "$out/build" --parallel 4 > "$out/build.log" 2>&1
ldd "$out/build/probe" > "$out/ldd.txt"
if grep -q 'not found' "$out/ldd.txt"; then
  echo 'SBD preflight has unresolved libraries' >&2
  exit 1
fi
readelf -h "$out/build/probe" > "$out/elf.txt"
grep -q AArch64 "$out/elf.txt"
timeout --signal=TERM --kill-after=20s 180s mpirun -n 4 --bind-to core \
  --map-by ppr:4:node:PE=18 "$out/build/probe" "$out" > "$out/stdout" 2> "$out/stderr"
for rank in 0 1 2 3; do
  file="$out/rank.$rank.libraries.txt"
  grep -Fq "$OMPI_HOME/lib/libmpi" "$file"
  grep -Fq "$OMPI_HOME/lib/libpmix" "$file"
  grep -Fq "$SBD_FLOW2_NVPL_ROOT/lib/libnvpl_blas_lp64_seq.so" "$file"
  grep -Fq "$SBD_FLOW2_NVPL_ROOT/lib/libnvpl_lapack_lp64_seq.so" "$file"
  grep -q libgomp "$file"
  if grep -Eq 'libnvomp|libnvpl_(blas|lapack)_(ilp64|lp64_gomp)' "$file"; then
    echo 'SBD preflight loaded an unexpected ABI or OpenMP runtime' >&2
    exit 1
  fi
  while IFS= read -r library; do sha256sum "$library"; done < "$file" > "$out/rank.$rank.libraries.sha256"
done
printf '4 ranks x18 threads; sum6; dgemm/dsyev and runtime libraries passed\n' > "$out/PASSED"
