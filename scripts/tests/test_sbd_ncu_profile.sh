#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping SBD NCU profile test"
  exit 0
fi

source "${REPO_DIR}/scripts/bk_functions.sh"
export SBD_BENCHKIT_ROOT="${REPO_DIR}"
source "${REPO_DIR}/programs/sbd/profile.sh"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

FAKE_BIN="${TMP_DIR}/bin"
RUN_DIR="${TMP_DIR}/run"
RESULTS_DIR="${TMP_DIR}/results"
FAKE_NCU_LOG="${TMP_DIR}/ncu-kernels.log"
export FAKE_NCU_LOG RESULTS_DIR

mkdir -p "${FAKE_BIN}" "${RUN_DIR}" "${RESULTS_DIR}"

cat > "${FAKE_BIN}/mpirun" <<'EOF'
#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "-np" ]; then
  shift 2
fi

OMPI_COMM_WORLD_RANK=0 OMPI_COMM_WORLD_LOCAL_RANK=0 "$@"
EOF

cat > "${FAKE_BIN}/nsys" <<'EOF'
#!/bin/bash
set -euo pipefail

case "${1:-}" in
  profile)
    shift
    output=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -o)
          shift
          output="$1"
          ;;
        --*)
          ;;
        *)
          break
          ;;
      esac
      shift || true
    done
    test -n "$output"
    "$@" >/dev/null
    mkdir -p "$(dirname "$output")"
    printf 'fake nsys report\n' > "${output}.nsys-rep"
    ;;
  stats)
    shift
    output=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --output)
          shift
          output="$1"
          ;;
      esac
      shift || true
    done
    test -n "$output"
    cat > "${output}_cuda_gpu_kern_sum.csv" <<'CSV'
CUDA Kernel Summary
"Time (%)","Total Time (ns)","Instances","Avg (ns)","Med (ns)","Min (ns)","Max (ns)","StdDev (ns)","Name"
58.5,"5,850,000",50,117000,116000,100000,130000,4000,"void sbd::MultAlphaBeta<double>(double*, double const*)"
19.2,"1,920,000",50,38400,38000,35000,42000,2000,"void sbd::MultUnified<double, (int)0, (int)1>(double*, double const*)"
17.0,"1,700,000",50,34000,33800,30000,39000,1800,"void sbd::MultUnified<double, (int)1, (int)1>(double*, double const*)"
2.7,"270,000",50,5400,5300,5000,6500,400,"void sbd::MultUnified<double, (int)0, (int)0>(double*, double const*)"
2.5,"250,000",50,5000,4900,4500,6000,350,"void sbd::MultUnified<double, (int)1, (int)0>(double*, double const*)"
CSV
    printf 'Name,Time\ncuLaunchKernel,1\n' > "${output}_cuda_api_sum.csv"
    ;;
  *)
    exit 2
    ;;
esac
EOF

cat > "${FAKE_BIN}/ncu" <<'EOF'
#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "--import" ]; then
  printf 'metric,value\nfake,1\n'
  exit 0
fi

output=""
kernel=""
launch_count=""
launch_count_seen=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--output)
      shift
      output="$1"
      ;;
    --kernel-name)
      shift
      kernel="$1"
      ;;
    --launch-count)
      launch_count_seen=$((launch_count_seen + 1))
      shift
      launch_count="$1"
      ;;
    --launch-count=*)
      launch_count_seen=$((launch_count_seen + 1))
      launch_count="${1#--launch-count=}"
      ;;
    --kernel-name-base|--launch-skip|--target-processes|--set)
      shift
      ;;
    --nvtx)
      ;;
    ./*)
      "$@" >/dev/null
      break
      ;;
  esac
  shift || true
done

test -n "$output"
if [ "${FAKE_NCU_FAIL:-}" = "1" ]; then
  exit 7
fi
mkdir -p "$(dirname "$output")"
printf '%s\tlaunch_count=%s\tlaunch_count_seen=%s\n' "$kernel" "$launch_count" "$launch_count_seen" >> "$FAKE_NCU_LOG"
printf 'fake ncu report\n' > "${output}.ncu-rep"
EOF

cat > "${RUN_DIR}/diag" <<'EOF'
#!/bin/bash
set -euo pipefail
printf 'fake SBD diag\n'
EOF

chmod +x "${FAKE_BIN}/mpirun" "${FAKE_BIN}/nsys" "${FAKE_BIN}/ncu" "${RUN_DIR}/diag"
export PATH="${FAKE_BIN}:${PATH}"

(
  unset BK_PROFILER BK_PROFILER_LEVEL BK_SBD_NCU_PROFILE BK_SBD_NCU_PROFILER_LEVEL SBD_PROFILER_TOOL
  sbd_configure_ncu_profile_from_run_env RC_FX700
  test -z "${BK_SBD_NCU_PROFILE:-}"
)

(
  unset BK_PROFILER BK_PROFILER_LEVEL BK_SBD_NCU_PROFILE BK_SBD_NCU_PROFILER_LEVEL
  export SBD_PROFILER_TOOL=none
  sbd_configure_ncu_profile_from_run_env RIKYU
  test "${BK_SBD_NCU_PROFILE:-}" = "false"
)

(
  unset BK_PROFILER BK_PROFILER_LEVEL BK_SBD_NCU_PROFILE BK_SBD_NCU_PROFILER_LEVEL
  unset BK_SBD_NCU_PLAN_TOP_K BK_SBD_NCU_PLAN_LAUNCH_COUNT BK_SBD_NCU_PROFILE_TIMEOUT_SECONDS
  unset SBD_PROFILER_TOOL
  sbd_configure_ncu_profile_from_run_env RIKYU
  test "${BK_SBD_NCU_PROFILE}" = "true"
  test "${BK_SBD_NCU_PROFILER_LEVEL}" = "single"
  test "${BK_SBD_NCU_PLAN_TOP_K}" = "1"
  test "${BK_SBD_NCU_PLAN_LAUNCH_COUNT}" = "1"
  case "${BK_SBD_NCU_PROFILE_TIMEOUT_SECONDS}" in
    ''|0|*[!0-9]*) exit 1 ;;
  esac
)

test "$(sbd_strip_ncu_launch_count_args --set basic --launch-count 1 --nvtx --launch-count=3)" = "--set basic --nvtx"

(
  export BK_SBD_NCU_PROFILE=true
  sbd_run_configured_ncu_profiles() { return 7; }
  sbd_run_optional_ncu_profiles RIKYU 4
)

pushd "${RUN_DIR}" >/dev/null
unset BK_PROFILER SBD_PROFILER_TOOL BK_SBD_NCU_PROFILE BK_SBD_NCU_PROFILER_LEVEL BK_SBD_NCU_PLAN_LAUNCH_COUNT
export BK_SBD_NCU_PROFILE_MODE=discovery
export BK_SBD_NCU_PLAN_TOP_K=5
export BK_PROFILER_LEVEL=single
sbd_configure_ncu_profile_from_run_env RIKYU
test "${BK_SBD_NCU_PROFILE}" = "true"
test "${BK_SBD_NCU_PROFILER_LEVEL}" = "single"
sbd_init_stage_timing timing-test
bash -c 'test "$SBD_STAGE_TIMING_READY" = true'
jq -e '.exp == "timing-test" and .stages == []' \
  "${RESULTS_DIR}/sbd_stage_timing.json" >/dev/null
sbd_run_configured_ncu_profiles RIKYU 4 \
  --fcidump fcidump.txt \
  --adetfile h2o-1em7-alpha.txt
popd >/dev/null

test -f "${RESULTS_DIR}/sbd_nsys_kernel_discovery.nsys-rep"
test -f "${RESULTS_DIR}/sbd_nsys_stats_cuda_gpu_kern_sum.csv"
test -f "${RESULTS_DIR}/sbd_kernel_discovery.json"
test -f "${RESULTS_DIR}/sbd_ncu_plan.json"

jq -e '
  (.profiles | length) == 5 and
  ([.profiles[].launch_count] | unique) == [1] and
  ([.profiles[].kernel_match.pattern] | unique | length) == 5 and
  .profiles[1].kernel_match.pattern == "regex:.*sbd::MultUnified<double,[[:space:]]*\\(int\\)0,[[:space:]]*\\(int\\)1>.*" and
  .profiles[4].kernel_match.pattern == "regex:.*sbd::MultUnified<double,[[:space:]]*\\(int\\)1,[[:space:]]*\\(int\\)0>.*"
' "${RESULTS_DIR}/sbd_ncu_plan.json" >/dev/null

mapfile -t profile_archives < <(find "${RESULTS_DIR}" -maxdepth 1 -type f -name 'padata_*.tgz' | sort)
mapfile -t profile_metadata < <(find "${RESULTS_DIR}" -maxdepth 1 -type f -name 'padata_*.metadata.json' | sort)
test "${#profile_archives[@]}" -eq 5
test "${#profile_metadata[@]}" -eq 5

artifact_count=$(printf '%s\n' "${SBD_MULT_SECTION_ARTIFACTS}" | tr ',' '\n' | awk 'NF { count += 1 } END { print count + 0 }')
test "$artifact_count" -eq 12
printf '%s\n' "${SBD_MULT_SECTION_ARTIFACTS}" | tr ',' '\n' | grep -Fxq 'results/sbd_kernel_discovery.json'
printf '%s\n' "${SBD_MULT_SECTION_ARTIFACTS}" | tr ',' '\n' | grep -Fxq 'results/sbd_ncu_plan.json'
printf '%s\n' "${SBD_MULT_SECTION_ARTIFACTS}" | tr ',' '\n' | grep -Eq '^results/padata_.*\.metadata\.json$'

jq -e '
  .kind == "gpu_kernel_profile_metadata" and
  .profiler == "ncu" and
  .section == "mult" and
  .nsys_discovery.section == "mult" and
  (.nsys_discovery.kernel_match.pattern | contains("MultUnified"))
' "${profile_metadata[1]}" >/dev/null

for archive in "${profile_archives[@]}"; do
  tar -tzf "$archive" | grep -q 'bk_profiler_artifact/meta.json'
  tar -tzf "$archive" | grep -q 'bk_profiler_artifact/raw/rep1/profile_raw.csv'
  if tar -tzf "$archive" | grep -q '.ncu-rep$'; then
    echo "SBD profile archive should omit .ncu-rep by default" >&2
    exit 1
  fi
done

grep -Fq 'regex:.*sbd::MultUnified<double,[[:space:]]*\(int\)0,[[:space:]]*\(int\)1>.*' "$FAKE_NCU_LOG"
awk -F '\t' '$2 != "launch_count=1" || $3 != "launch_count_seen=1" { bad = 1 } END { exit bad }' "$FAKE_NCU_LOG"

TIMING_FILE="${RESULTS_DIR}/sbd_stage_timing.json"
jq -e --slurpfile plan "${RESULTS_DIR}/sbd_ncu_plan.json" '
  .schema_version == 1 and .kind == "sbd_stage_timing" and
  .producer == "sbd" and .exp == "timing-test" and
  .elapsed_clock == "monotonic" and
  (.stages | length) == (3 + ($plan[0].profiles | length)) and
  [.stages[0:3][].stage] == ["nsys_collect", "nsys_export", "ncu_plan"] and
  all(.stages[0:3][]; .profile == "") and
  all(.stages[3:][]; .stage == "ncu_collect") and
  ([.stages[].id] | unique | length) == (.stages | length) and
  all(.stages[];
    (.id | type == "string" and length > 0) and
    .status == "completed" and .exit_code == 0 and
    (.started_at | type == "string" and length > 0) and
    (.finished_at | type == "string" and length > 0) and
    (.elapsed_seconds | type == "number" and . >= 0) and
    (has("started_monotonic_ns") | not))
' "$TIMING_FILE" >/dev/null

profile_index=3
while IFS= read -r profile_name; do
  profile_slug=$(bk_profile_slug "$profile_name")
  jq -e --argjson index "$profile_index" --arg profile "$profile_slug" \
    '.stages[$index].profile == $profile' "$TIMING_FILE" >/dev/null
  profile_index=$((profile_index + 1))
done < <(jq -r '.profiles[].name' "${RESULTS_DIR}/sbd_ncu_plan.json")

jq -e '
  .schema_version == 1 and (.observations | length) == 1 and
  (.observations[0] |
    .id == "sbd-stage-timing" and .kind == "workflow-stage-timing" and
    .producer == "sbd" and .result_exp == "timing-test" and
    .format == "sbd_stage_timing/v1" and
    .artifact.type == "file_reference" and
    .artifact.path == "results/sbd_stage_timing.json")
' "${RESULTS_DIR}/timing_observations.json" >/dev/null
cp "$TIMING_FILE" "${TMP_DIR}/successful-timing.json"

# Inspect the artifact from inside the command, before the wrapper can finish it.
cat > "${FAKE_BIN}/timed-command" <<'EOF'
#!/bin/bash
set -euo pipefail
timing_file="$1"
status="$2"
jq -e '
  .stages[-1] |
  .stage == "benchmark" and .profile == "probe" and .status == "running" and
  (.started_at | type == "string" and length > 0) and
  (.started_monotonic_ns | type == "number" and . > 0) and
  (has("finished_at") | not) and (has("elapsed_seconds") | not) and
  (has("exit_code") | not)
' "$timing_file" >/dev/null
cp "$timing_file" "${timing_file}.running"
printf 'command stdout\n'
printf 'command stderr\n' >&2
exit "$status"
EOF
chmod +x "${FAKE_BIN}/timed-command"

# Exercise both output routes, including timeout status without a real wait.
for log_route in direct file; do
  for expected_status in 0 7 124; do
    command_log=""
    if [ "$log_route" = file ]; then
      command_log="${TMP_DIR}/command.log"
    fi
    actual_status=0
    command_output=$(sbd_time_command benchmark probe "$command_log" \
      timed-command "$TIMING_FILE" "$expected_status" \
      2>"${TMP_DIR}/timing-stderr.log") || actual_status=$?
    test "$actual_status" -eq "$expected_status"
    if [ "$log_route" = direct ]; then
      test "$command_output" = "command stdout"
      grep -Fxq 'command stderr' "${TMP_DIR}/timing-stderr.log"
    else
      test -z "$command_output"
      test "$(cat "$command_log")" = $'command stdout\ncommand stderr'
    fi
    jq -e --argjson status "$expected_status" \
      --slurpfile running "${TIMING_FILE}.running" '
      .stages[-1] as $finished |
      $running[0].stages[-1] as $started |
      .stages[0:-1] == $running[0].stages[0:-1] and
      $finished.id == $started.id and $finished.started_at == $started.started_at and
      $finished.stage == $started.stage and $finished.profile == $started.profile and
      $finished.exit_code == $status and
      $finished.status == (if $status == 0 then "completed" else "failed" end) and
      ($finished.finished_at | type == "string" and length > 0) and
      ($finished.elapsed_seconds | type == "number" and . >= 0) and
      ($finished | has("started_monotonic_ns") | not)
    ' "$TIMING_FILE" >/dev/null
  done
done

# A terminated wrapper must leave its persisted start visibly incomplete.
interrupted_status=0
bash -c '
  trap - EXIT
  trap "exit 143" TERM
  source "$SBD_BENCHKIT_ROOT/programs/sbd/profile.sh"
  sbd_time_command interrupted probe "" bash -c '\''kill -TERM "$PPID"'\''
' >"${TMP_DIR}/interrupted.log" 2>&1 || interrupted_status=$?
test "$interrupted_status" -eq 143
jq -e '
  .stages[-1] | .stage == "interrupted" and .status == "running" and
  has("started_monotonic_ns") and (has("finished_at") | not) and
  (has("elapsed_seconds") | not) and (has("exit_code") | not)
' "$TIMING_FILE" >/dev/null

# Logger failures must not replace either successful or failed command status.
cp "$TIMING_FILE" "${TMP_DIR}/before-unavailable.json"
(
  export RESULTS_DIR="${TMP_DIR}/unavailable-results"
  mkdir -p "$RESULTS_DIR"
  cp "$TIMING_FILE" "${RESULTS_DIR}/sbd_stage_timing.json"
  PYTHON_BIN="${TMP_DIR}/missing-python" sbd_init_stage_timing unavailable \
    2>"${TMP_DIR}/unavailable.log"
  test "$SBD_STAGE_TIMING_READY" = false
  test ! -e "${RESULTS_DIR}/sbd_stage_timing.json"
  test ! -e "${RESULTS_DIR}/timing_observations.json"
  actual_status=0
  sbd_time_command unavailable "" "" bash -c 'exit 7' || actual_status=$?
  test "$actual_status" -eq 7
  test ! -e "${RESULTS_DIR}/sbd_stage_timing.json"
)
for expected_status in 0 7 124; do
  actual_status=0
  command_output=$(PYTHON_BIN="${TMP_DIR}/missing-python" \
    sbd_time_command unavailable "" "" bash -c 'printf "plan.json\n"; exit "$1"' \
    bash "$expected_status" 2>>"${TMP_DIR}/unavailable.log") || actual_status=$?
  test "$actual_status" -eq "$expected_status"
  test "$command_output" = plan.json
done
cmp "$TIMING_FILE" "${TMP_DIR}/before-unavailable.json"

(
  set -e
  export RESULTS_DIR="${TMP_DIR}/registration-failure-results"
  bk_record_timing_observation() {
    printf '{malformed\n' > "$BK_TIMING_OBSERVATIONS_FILE"
    rm() { return 7; }
    return 7
  }
  sbd_init_stage_timing registration-failure \
    2>"${TMP_DIR}/registration-failure.log"
  unset -f bk_record_timing_observation rm
  test "$SBD_STAGE_TIMING_READY" = true
  test ! -e "${RESULTS_DIR}/timing_observations.json"
  test ! -e "${RESULTS_DIR}/.timing_observation_items.jsonl"
  test "$(sbd_time_command benchmark "" "" printf 'measured output\n')" = "measured output"
  jq -e '.exp == "registration-failure" and (.stages | length) == 1 and
    (.stages[0] | .stage == "benchmark" and .status == "completed" and .exit_code == 0)' \
    "${RESULTS_DIR}/sbd_stage_timing.json" >/dev/null
  test ! -e "${RESULTS_DIR}/timing_observations.json"
)

(
  set -e
  export RESULTS_DIR="${TMP_DIR}/reset-failure-results"
  mkdir -p "$RESULTS_DIR"
  cp "$TIMING_FILE" "${RESULTS_DIR}/sbd_stage_timing.json"
  export SBD_STAGE_TIMING_READY=true
  rm() { return 7; }
  sbd_init_stage_timing reset-failure \
    2>"${TMP_DIR}/reset-failure.log"
  unset -f rm
  bash -c 'test "$SBD_STAGE_TIMING_READY" = false'
  actual_status=0
  sbd_time_command disabled "" "" bash -c 'exit 7' || actual_status=$?
  test "$actual_status" -eq 7
  cmp "$TIMING_FILE" "${RESULTS_DIR}/sbd_stage_timing.json"
  test ! -e "${RESULTS_DIR}/timing_observations.json"
)

timing_python_without_finish() {
  if [ "${3:-}" = finish ]; then
    return 9
  fi
  "${PYTHON_BIN_FOR_TEST}" "$@"
}
PYTHON_BIN_FOR_TEST="${PYTHON_BIN:-python3}"
for expected_status in 0 7 124; do
  actual_status=0
  PYTHON_BIN=timing_python_without_finish sbd_time_command finish_unavailable "" "" \
    bash -c 'exit "$1"' bash "$expected_status" \
    2>>"${TMP_DIR}/unavailable.log" || actual_status=$?
  test "$actual_status" -eq "$expected_status"
  jq -e '.stages[-1] | .stage == "finish_unavailable" and .status == "running" and
    (has("exit_code") | not) and (has("elapsed_seconds") | not)' "$TIMING_FILE" >/dev/null
done

jq -e --slurpfile successful "${TMP_DIR}/successful-timing.json" '
  .exp == $successful[0].exp and
  .stages[0:($successful[0].stages | length)] == $successful[0].stages
' "$TIMING_FILE" >/dev/null

echo "SBD NCU profile test passed"
