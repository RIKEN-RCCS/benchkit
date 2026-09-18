#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-python3}"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT
trap 'echo "workflow timing test failed at line $LINENO" >&2' ERR

source "${REPO_DIR}/scripts/bk_functions.sh"
RECORDER="${REPO_DIR}/scripts/profiling/workflow_timing.py"
RESULTS_DIR="${TMP_DIR}/results"
export RESULTS_DIR
mkdir -p "$RESULTS_DIR" "${TMP_DIR}/nested/work" "${TMP_DIR}/bin"

manifest() {
  "$PYTHON_BIN" "$RECORDER" --results-dir "$RESULTS_DIR" manifest
}

timing_file() {
  local relative
  relative=$(manifest | jq -er --arg exp "$1" \
    '.observations[] | select((.result_exp // "") == $exp) | .artifact.path')
  printf '%s/%s\n' "$RESULTS_DIR" "${relative#results/}"
}

# Context declaration must be lazy, including when the directory already exists.
bk_run_context --results-dir "$RESULTS_DIR" --exp CASE0
test -z "$(find "$RESULTS_DIR" -name 'workflow_timing_*.json' -print -quit)"
manifest | jq -e '.schema_version == 1 and .observations == []' >/dev/null

probe_command() {
  local file
  file=$(timing_file CASE0)
  jq -e '
    .schema_version == 1 and .kind == "workflow_stage_timing" and
    .producer == "benchkit" and .exp == "CASE0" and
    .elapsed_clock == "monotonic" and
    (.session_id | type == "string" and length > 0) and
    (.stages[-1] |
      .stage == "benchmark" and .tool == "none" and .status == "running" and
      (.id | type == "string" and length > 0) and
      (.started_at | type == "string" and length > 0) and
      (.started_monotonic_ns | type == "number" and . > 0) and
      (has("finished_at") | not) and (has("elapsed_seconds") | not) and
      (has("exit_code") | not))
  ' "$file" >/dev/null || return 99
  cp "$file" "${TMP_DIR}/running.json" || return 99
  printf 'command stdout\n'
  printf 'command stderr\n' >&2
  return "$1"
}

for route in direct file; do
  for expected_status in 0 7 124; do
    args=()
    if [ "$route" = file ]; then
      args=(--log "${TMP_DIR}/command.log")
    fi
    actual_status=0
    output=$(bk_run "${args[@]}" -- probe_command "$expected_status" \
      2>"${TMP_DIR}/stderr.log") || actual_status=$?
    test "$actual_status" -eq "$expected_status"
    if [ "$route" = direct ]; then
      test "$output" = 'command stdout'
      grep -Fxq 'command stderr' "${TMP_DIR}/stderr.log"
    else
      test -z "$output"
      test "$(cat "${TMP_DIR}/command.log")" = $'command stdout\ncommand stderr'
    fi
    TIMING_FILE=$(timing_file CASE0)
    jq -e --argjson status "$expected_status" --slurpfile running "${TMP_DIR}/running.json" '
      .stages[-1] as $finished | $running[0].stages[-1] as $started |
      .stages[0:-1] == $running[0].stages[0:-1] and
      $finished.id == $started.id and $finished.started_at == $started.started_at and
      $finished.stage == $started.stage and $finished.tool == $started.tool and
      $finished.exit_code == $status and
      $finished.status == (if $status == 0 then "completed" else "failed" end) and
      ($finished.finished_at | type == "string" and length > 0) and
      ($finished.elapsed_seconds | type == "number" and . >= 0)
    ' "$TIMING_FILE" >/dev/null
  done
done
cp "$TIMING_FILE" "${TMP_DIR}/known.json"

# Absolute context survives cwd changes, substitutions, child shells and pipes.
(
  cd "${TMP_DIR}/nested/work"
  bk_run -- printf 'pipeline output\n' | tee "${TMP_DIR}/pipeline.log" >/dev/null
  test "$(bk_run -- pwd)" = "$PWD"
  bash -c 'source "$1/scripts/bk_functions.sh"; bk_run -- true' bash "$REPO_DIR"
  test ! -d results
)
test "$(cat "${TMP_DIR}/pipeline.log")" = 'pipeline output'
jq -e '(.stages | length) == 9' "$TIMING_FILE" >/dev/null
actual_status=0
bk_run -- bash -c 'exit 7' | cat >/dev/null || actual_status=$?
test "$actual_status" -eq 7
test "$(bk_run -- printf 'two timed pipeline commands' | bk_run -- cat)" = 'two timed pipeline commands'
(
  set +e
  bk_run -- false
  test "$?" -eq 1
  case "$-" in *e*) exit 1 ;; esac
)

for tool in nsys ncu fapp; do
  for phase in collect export plan; do
    bk_profile_execute --tool "$tool" --phase "$phase" --profile 'sample profile' \
      --log "${TMP_DIR}/profile.log" -- printf '%s\n' "$tool:$phase"
    test "$(cat "${TMP_DIR}/profile.log")" = "$tool:$phase"
    jq -e --arg tool "$tool" --arg phase "$phase" '
      .stages[-1] | .tool == $tool and .stage == $phase and
      .profile == "sample profile" and .status == "completed" and .exit_code == 0
    ' "$TIMING_FILE" >/dev/null
  done
done
actual_status=0
bk_profile_execute --tool ncu --phase collect -- bash -c 'exit 23' || actual_status=$?
test "$actual_status" -eq 23
jq -e '.stages[-1] | .status == "failed" and .exit_code == 23' "$TIMING_FILE" >/dev/null

bk_generate_ncu_plan \
  --nsys-csv "${REPO_DIR}/scripts/tests/fixtures/nsys_cuda_gpu_kern_sum.csv" \
  --out-discovery "${RESULTS_DIR}/kernel_discovery.json" \
  --out-plan "${RESULTS_DIR}/ncu_plan.json" --top-k 1 >/dev/null
jq -e '.profiles | length == 1' "${RESULTS_DIR}/ncu_plan.json" >/dev/null
jq -e '.stages[-1] | .stage == "plan" and .tool == "ncu" and .exit_code == 0' \
  "$TIMING_FILE" >/dev/null
actual_status=0
bk_generate_ncu_plan --nsys-csv "${TMP_DIR}/missing.csv" \
  --out-plan "${TMP_DIR}/missing-plan.json" >"${TMP_DIR}/bad-plan.log" 2>&1 || actual_status=$?
test "$actual_status" -ne 0
jq -e --argjson status "$actual_status" '.stages[-1] |
  .stage == "plan" and .tool == "ncu" and .status == "failed" and .exit_code == $status' \
  "$TIMING_FILE" >/dev/null

# Interrupt the shell, not just its child: only the persisted start may remain.
actual_status=0
bash -c '
  source "$1/scripts/bk_functions.sh"
  trap "exit 143" TERM
  bk_run -- bash -c '\''kill -TERM "$PPID"'\''
' bash "$REPO_DIR" >"${TMP_DIR}/interrupted.log" 2>&1 || actual_status=$?
test "$actual_status" -eq 143
jq -e '.stages[-1] | .status == "running" and has("started_monotonic_ns") and
  (has("finished_at") | not) and (has("elapsed_seconds") | not) and
  (has("exit_code") | not)' "$TIMING_FILE" >/dev/null

# Recorder unavailability must neither clobber known records nor mask status.
cp "$TIMING_FILE" "${TMP_DIR}/before-unavailable.json"
for expected_status in 0 7 124; do
  actual_status=0
  output=$(PYTHON_BIN="${TMP_DIR}/missing-python" bk_run -- \
    bash -c 'printf "plan.json\n"; exit "$1"' bash "$expected_status" \
    2>"${TMP_DIR}/unavailable.log") || actual_status=$?
  test "$actual_status" -eq "$expected_status"
  test "$output" = plan.json
done
cmp "$TIMING_FILE" "${TMP_DIR}/before-unavailable.json"

timing_python_without_finish() {
  local arg
  for arg in "$@"; do
    if [ "$arg" = finish ]; then
      return 9
    fi
  done
  "$PYTHON_FOR_TEST" "$@"
}
PYTHON_FOR_TEST="$PYTHON_BIN"
for expected_status in 0 7 124; do
  actual_status=0
  PYTHON_BIN=timing_python_without_finish bk_run -- bash -c 'exit "$1"' bash "$expected_status" \
    2>"${TMP_DIR}/finish-unavailable.log" || actual_status=$?
  test "$actual_status" -eq "$expected_status"
  jq -e '.stages[-1] | .status == "running" and
    (has("exit_code") | not) and (has("elapsed_seconds") | not)' "$TIMING_FILE" >/dev/null
done
cp "$TIMING_FILE" "${TMP_DIR}/before-unavailable.json"
jq -e --slurpfile known "${TMP_DIR}/known.json" '
  .session_id == $known[0].session_id and
  .stages[0:($known[0].stages | length)] == $known[0].stages and
  ([.stages[].id] | unique | length) == (.stages | length)
' "$TIMING_FILE" >/dev/null

# Different experiments in the same results directory must not replace CASE0.
bk_run_context --results-dir "$RESULTS_DIR" --exp CASE1
bk_run -- true
CASE1_FILE=$(timing_file CASE1)
test "$CASE1_FILE" != "$TIMING_FILE"
cmp "$TIMING_FILE" "${TMP_DIR}/before-unavailable.json"
bk_run_context --results-dir "$RESULTS_DIR" --exp ''
bk_run -- true
manifest > "${TMP_DIR}/manifest.json"
jq -e '
  .schema_version == 1 and (.observations | length) == 3 and
  ([.observations[].id] | unique | length) == 3 and
  all(.observations[];
    .kind == "workflow-stage-timing" and .producer == "benchkit" and
    .format == "workflow_stage_timing/v1" and
    .artifact.type == "file_reference" and
    (.artifact.path | test("^results/workflow_timing_[a-zA-Z0-9]+\\.json$"))) and
  any(.observations[]; (has("result_exp") | not))
' "${TMP_DIR}/manifest.json" >/dev/null
"$PYTHON_BIN" - "$RESULTS_DIR" "${TMP_DIR}/manifest.json" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for observation in json.loads(pathlib.Path(sys.argv[2]).read_text())["observations"]:
    stages = json.loads((root / pathlib.Path(observation["artifact"]["path"]).name).read_text())["stages"]
    assert observation["summary"] == {
        "stage_count": len(stages),
        "completed_count": sum(stage["status"] == "completed" for stage in stages),
        "failed_count": sum(stage["status"] == "failed" for stage in stages),
        "unfinished_count": sum(stage["status"] not in {"completed", "failed"} for stage in stages),
    }
PY
test ! -e "${RESULTS_DIR}/timing_observations.json"
test ! -e "${RESULTS_DIR}/.timing_observation_items.jsonl"

# Result emission must discover common artifacts without app registration.
cat > "${RESULTS_DIR}/result" <<'EOF'
FOM:1.25 FOM_unit:s Exp:CASE0 node_count:1 numproc_node:1 nthreads:1
FOM:2.50 FOM_unit:s Exp:CASE1 node_count:1 numproc_node:1 nthreads:1
EOF
cat > "${RESULTS_DIR}/pipeline_timing.json" <<'EOF'
{"build_time":12,"queue_time":0,"run_time":34}
EOF
(
  cd "$TMP_DIR"
  bash "${REPO_DIR}/scripts/result.sh" demoapp DemoSystem cross build_job run_job 42 >/dev/null
)
jq -e '(.timing_observations.observations | length) == 2' \
  "${RESULTS_DIR}/result0.json" >/dev/null

# Existing QWS detailed timing stays alongside the common workflow records.
cat > "${RESULTS_DIR}/qws_timing_CASE0.json" <<'EOF'
{"schema_version":1,"kind":"qws_timing_observation","producer":"qws","exp":"CASE0","timers":[]}
EOF
cat > "${RESULTS_DIR}/timing_observations.json" <<'EOF'
{"schema_version":1,"observations":[{"id":"qws-case0","kind":"detailed-timing","producer":"qws","format":"qws_timing_observation/v1","result_exp":"CASE0","artifact":{"type":"file_reference","path":"results/qws_timing_CASE0.json"},"summary":{"timer_count":0}}]}
EOF
cp "${RESULTS_DIR}/timing_observations.json" "${TMP_DIR}/qws-manifest.json"
(
  cd "$TMP_DIR"
  bash "${REPO_DIR}/scripts/result.sh" qws DemoSystem cross build_job run_job 42 >/dev/null
)
cmp "${RESULTS_DIR}/timing_observations.json" "${TMP_DIR}/qws-manifest.json"
for index in 0 1; do
  jq -e --arg exp "CASE$index" --argjson count "$((3 - index))" '
    .Exp == $exp and
    (.timing_observations.observations | length) == $count and
    all(.timing_observations.observations[]; (.result_exp // $exp) == $exp) and
    ([.timing_observations.observations[] | select(.producer == "benchkit")] | length) == 2 and
    .pipeline_timing.build_time == 12 and .pipeline_timing.queue_time == 0 and
    .pipeline_timing.run_time == 34 and (has("fom_breakdown") | not)
  ' "${RESULTS_DIR}/result${index}.json" >/dev/null
done
jq -e '.FOM == "1.25" and any(.timing_observations.observations[]; .id == "qws-case0")' \
  "${RESULTS_DIR}/result0.json" >/dev/null
jq -e '.FOM == "2.50"' "${RESULTS_DIR}/result1.json" >/dev/null

# Exercise the real sender; curl alone is mocked, so no network is possible.
cat > "${TMP_DIR}/bin/curl" <<'EOF'
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" >> "$CURL_LOG"
case "$*" in
  */api/ingest/result*) printf '%s\n' '{"id":"11111111-2222-3333-4444-555555555555","timestamp":"20260101_000000"}' ;;
  *) printf '%s\n' '{"status":"uploaded"}' ;;
esac
EOF
chmod +x "${TMP_DIR}/bin/curl"
touch "${TMP_DIR}/client.crt" "${TMP_DIR}/client.key"
(
  cd "$TMP_DIR"
  export PATH="${TMP_DIR}/bin:$PATH" CURL_LOG="${TMP_DIR}/curl.log"
  export RESULT_SERVER=https://example.invalid
  export RESULT_SERVER_CLIENT_CERT="${TMP_DIR}/client.crt"
  export RESULT_SERVER_CLIENT_KEY="${TMP_DIR}/client.key"
  bash "${REPO_DIR}/scripts/result_server/send_results.sh" >"${TMP_DIR}/sender.log" 2>&1
)
while IFS= read -r artifact; do
  grep -F 'measurement-artifact' "${TMP_DIR}/curl.log" | grep -Fq "artifact_path=$artifact"
done < <(jq -r '.observations[].artifact.path' "${TMP_DIR}/manifest.json")
grep -F 'measurement-artifact' "${TMP_DIR}/curl.log" | grep -Fq 'artifact_path=results/qws_timing_CASE0.json'

# GENESIS uses its actual launch builders with fake host/container profilers.
cat > "${TMP_DIR}/bin/ncu" <<'EOF'
#!/bin/bash
set -euo pipefail
if [ "${1:-}" = --import ]; then
  printf 'metric,value\nfake,1\n'
  exit 0
fi
output=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    --target-processes|--set|--launch-count|--kernel-name-base|--kernel-name|--launch-skip) shift 2 ;;
    --nvtx) shift ;;
    *) break ;;
  esac
done
test -n "$output"
mkdir -p "$(dirname "$output")"
printf 'fake report\n' > "${output}.ncu-rep"
"$@"
EOF
cat > "${TMP_DIR}/bin/nsys" <<'EOF'
#!/bin/bash
set -euo pipefail
mode="$1"
shift
output=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o|--output) output="$2"; shift 2 ;;
    --report|--format) shift 2 ;;
    --*) shift ;;
    *) break ;;
  esac
done
test -n "$output"
if [ "$mode" = profile ]; then
  "$@"
  printf 'fake report\n' > "${output}.nsys-rep"
else
  cp "$GENESIS_TEST_CSV" "$output"
fi
EOF
cat > "${TMP_DIR}/bin/apptainer" <<'EOF'
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" >> "$GENESIS_CONTAINER_LOG"
test "$1" = exec
shift
while [ "$#" -gt 0 ]; do
  case "$1" in
    --nv) shift ;;
    --bind|--pwd) shift 2 ;;
    *) shift; break ;;
  esac
done
# Preserve the fake tool PATH through GENESIS's container login-shell payload.
if [ "${1:-}" = bash ] && [ "${2:-}" = -lc ]; then
  shift 2
  exec bash -c "$@"
fi
exec "$@"
EOF
chmod +x "${TMP_DIR}/bin/ncu" "${TMP_DIR}/bin/nsys" "${TMP_DIR}/bin/apptainer"
for mode in host container; do
  (
    source "${REPO_DIR}/programs/genesis/profile.sh"
    export PATH="${TMP_DIR}/bin:$PATH"
    export GENESIS_TEST_CSV="${REPO_DIR}/scripts/tests/fixtures/nsys_cuda_gpu_kern_sum.csv"
    export GENESIS_CONTAINER_LOG="${TMP_DIR}/container.log"
    export BK_GENESIS_NCU_NSTEPS=off BK_GENESIS_NCU_PLAN_TOP_K=1
    export GENESIS_BENCHKIT_ROOT="$REPO_DIR"
    SCRIPT_DIR="$REPO_DIR"
    resultsdir="${TMP_DIR}/genesis-${mode}/results"
    RESULTS_DIR="$resultsdir"
    header=sample
    mkdir -p "$resultsdir"
    cd "${TMP_DIR}/genesis-${mode}"
    bk_run_context --results-dir "$resultsdir" --exp "GENESIS-${mode}"
    app=(bash -c 'printf "dynamics = 1.25\n"' bash sample.inp)
    if [ "$mode" = container ]; then
      app=(apptainer exec --nv --bind "$PWD:$PWD" --pwd "$PWD" sample.sif "${app[@]}")
    fi
    bk_run -- "${app[@]}" >/dev/null
    plan=$(genesis_generate_ncu_plan single "${app[@]}" 2>discovery.log)
    test -s "$plan"
    genesis_run_ncu_profile sample sample 'regex:.*sample.*' 0 1 single '' '{}' \
      "${app[@]}" >profile.log 2>&1
    jq -e '
      .producer == "benchkit" and
      any(.stages[]; .stage == "benchmark" and .tool == "none") and
      any(.stages[]; .stage == "collect" and .tool == "nsys") and
      any(.stages[]; .stage == "export" and .tool == "nsys") and
      any(.stages[]; .stage == "plan" and .tool == "ncu") and
      ([.stages[] | select(.stage == "collect" and .tool == "ncu")] | length) == 1 and
      ([.stages[] | select(.stage == "export" and .tool == "ncu")] | length) == 2 and
      all(.stages[]; .status == "completed" and .exit_code == 0)
    ' "$resultsdir"/workflow_timing_*.json >/dev/null
    test -f "$resultsdir/padata_sample.tgz"
    test ! -e "$resultsdir/timing_observations.json"
  )
done
grep -Fq 'nsys profile' "${TMP_DIR}/container.log"
grep -Fq 'nsys stats' "${TMP_DIR}/container.log"
grep -Fq 'ncu --import' "${TMP_DIR}/container.log"

# A new session excludes previous-run files without deleting their evidence.
cp "$TIMING_FILE" "${TMP_DIR}/previous-session.json"
(
  unset _BK_WORKFLOW_SESSION_ID
  source "${REPO_DIR}/scripts/bk_functions.sh"
  bk_run_context --results-dir "$RESULTS_DIR" --exp NEXT
  manifest | jq -e '.observations == []' >/dev/null
  bk_run -- true
  manifest | jq -e '(.observations | length) == 1 and
    .observations[0].result_exp == "NEXT"' >/dev/null
)
cmp "$TIMING_FILE" "${TMP_DIR}/previous-session.json"

# Failed context publication cannot leave an earlier session active for emission.
(
  unset _BK_WORKFLOW_SESSION_ID
  source "${REPO_DIR}/scripts/bk_functions.sh"
  PYTHON_BIN="${TMP_DIR}/missing-python" \
    bk_run_context --results-dir "$RESULTS_DIR" --exp UNAVAILABLE \
    2>"${TMP_DIR}/context-unavailable.log"
  manifest | jq -e '.schema_version == 1 and .observations == []' >/dev/null
  cd "$TMP_DIR"
  bash "${REPO_DIR}/scripts/result.sh" qws DemoSystem cross build_job run_job 42 >/dev/null
  jq -e '[.timing_observations.observations[] | .id] == ["qws-case0"]' \
    results/result0.json >/dev/null
  jq -e '(.timing_observations.observations // []) == []' results/result1.json >/dev/null
)
cmp "$TIMING_FILE" "${TMP_DIR}/previous-session.json"

echo "workflow timing tests passed"
