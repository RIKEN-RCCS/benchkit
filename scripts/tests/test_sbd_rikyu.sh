#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/work/programs" "$tmp/work/sbd/data/h2o"
ln -s "$root/scripts" "$tmp/work/scripts"
ln -s "$root/programs/sbd" "$tmp/work/programs/sbd"
module() { :; }
export -f module
cat > "$tmp/bin/cmake" <<'MOCK'
#!/bin/bash
set -euo pipefail
if [[ $1 = --build ]]; then
  [[ $3 = --parallel && $4 = 2 ]]
else
  [[ $* = *'-DSBD_USE_NVTX=ON'* && $* = *'-DSBD_GPU_ARCH=cc100'* ]]
  mkdir -p "$4/apps/chemistry_tpb_selected_basis_diagonalization"
  cp "$DIAG_FIXTURE" "$4/apps/chemistry_tpb_selected_basis_diagonalization/diag"
fi
MOCK
cat > "$tmp/bin/mpirun" <<'MOCK'
#!/bin/bash
set -euo pipefail
[[ $1 = -np && $2 = "$EXPECTED_RANKS" ]]
shift 2
OMPI_COMM_WORLD_LOCAL_RANK=0 "$@"
MOCK
cat > "$tmp/diag" <<'MOCK'
#!/bin/bash
set -euo pipefail
[[ ${OMP_NUM_THREADS:-} = "$EXPECTED_THREADS" ]]
[[ $* = *"--adetfile h2o-${EXPECTED_INPUT}-alpha.txt"* ]]
[[ $* = *'--task_comm_size 1'* ]]
[[ $* = *"--adet_comm_size $EXPECTED_COMM"* && $* = *"--bdet_comm_size $EXPECTED_COMM"* ]]
echo 'Elapsed time for davidson 0.5 seconds'
echo 'Elapsed time for mult 0.1 seconds'
echo " Energy = $EXPECTED_ENERGY"
MOCK
chmod +x "$tmp/bin/"* "$tmp/diag"
for input in fcidump.txt h2o-1em{4,5,6,7}-alpha.txt; do
  printf '%s\n' "$input" > "$tmp/work/sbd/data/h2o/$input"
done
(
  cd "$tmp/work"
  git -C sbd init -q
  git -C sbd add data
  git -C sbd -c user.name=Fixture -c user.email=fixture@example.invalid commit -qm fixture
  export PATH="$tmp/bin:$PATH" DIAG_FIXTURE="$tmp/diag" BK_BENCHKIT_ROOT="$tmp/work"
  bash programs/sbd/build.sh RIKYU
  test -x artifacts/diag
  test -s results/source_info.env
  for ranks in 1 4 8 16; do
    export EXPECTED_RANKS=$ranks EXPECTED_THREADS=32 EXPECTED_INPUT=1em7 EXPECTED_COMM=2 EXPECTED_ENERGY=-76.243776776861
    if [[ $ranks = 1 ]]; then
      export EXPECTED_THREADS=8 EXPECTED_INPUT=1em4 EXPECTED_COMM=1 EXPECTED_ENERGY=-76.2429584823075
    fi
    SBD_PROFILER_TOOL=none bash scripts/run_benchmark.sh programs/sbd/run.sh RIKYU "$((ranks == 1 ? 1 : ranks / 4))" "$((ranks == 1 ? 1 : 4))" "$EXPECTED_THREADS"
    grep -q "Exp:H2O-$EXPECTED_INPUT" results/result
    grep -q 'FOM:0.5' results/result
    jq -e '.status == "completed" and .exit_code == 0' results/execution.json > /dev/null
    digest=$(sha256sum "sbd_run/h2o-$EXPECTED_INPUT-alpha.txt" | awk '{print $1}')
    jq -e --arg digest "$digest" '[.inputs[].observation_capture.manifest.files[].sha256] | index($digest) != null' results/input_info.json > /dev/null
  done
)
(
  source "$root/scripts/bk_functions.sh"
  source "$root/programs/sbd/profile.sh"
  unset PYTHON_BIN BK_SBD_DAVIDSON_PROFILE
  n_ranks=1
  sbd_configure_ncu_profile_from_run_env RIKYU
  [[ $BK_SBD_DAVIDSON_PROFILE = true && $PYTHON_BIN = python3.12 ]]
  BK_SBD_DAVIDSON_PROFILE=false
  PYTHON_BIN=/chosen/python
  sbd_configure_ncu_profile_from_run_env RIKYU
  [[ $BK_SBD_DAVIDSON_PROFILE = false && $PYTHON_BIN = /chosen/python ]]
  unset BK_SBD_DAVIDSON_PROFILE
  n_ranks=4
  sbd_configure_ncu_profile_from_run_env RIKYU
  [[ -z ${BK_SBD_DAVIDSON_PROFILE:-} ]]
)
echo 'SBD RIKYU normal build/run and rank-specific profiling defaults passed'
