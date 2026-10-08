#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Assertions run on the test host; collectors see only ordinary shell utilities.
mkdir -p "$TMP_DIR/bin" "$TMP_DIR/work"
for tool in bash dirname basename mkdir date awk sed tr readlink sha256sum hostname uname mktemp rm getconf cat sort; do
  ln -s "$(command -v "$tool")" "$TMP_DIR/bin/$tool"
done
restricted_path="$TMP_DIR/bin"
PATH="$restricted_path" bash -c '! command -v jq; ! command -v curl; ! command -v python3'

value=$'a"b\\c\n\t\r\001\b\f\037 tail\n'
source "$REPO_DIR/scripts/json_output.sh"
bk_json_object string value "$value" json array '[]' > "$TMP_DIR/quoted.json"
jq -e --arg value "$value" '.value == $value and .array == []' "$TMP_DIR/quoted.json" >/dev/null
for ((code=1; code<32; code++)); do
  printf -v char '\\%03o' "$code"
  printf -v char '%b' "$char"
  bk_json_quote "$char" | jq -e --arg char "$char" '. == $char' >/dev/null
done
printf 'one\n\ntwo' | bk_json_lines_array | jq -e '. == ["one", "two"]' >/dev/null

export BK_SYSTEM='TestSystem'
export BK_EXECUTION_ACTIVITY="$value"
export BK_SNAPSHOT_ENV_VARS='CFLAGS SECRET_TOKEN INVALID-NAME CFLAGS'
export CFLAGS="$value" SECRET_TOKEN='never-publish-this'
export BK_SNAPSHOT_TOOL_COMMANDS='bash bash unavailable-compiler'
export LOADEDMODULES='compiler/test:mpi/test'
(
  cd "$TMP_DIR/work"
  PATH="$restricted_path" BK_SNAPSHOT_STAGE=run \
    bash "$REPO_DIR/scripts/collect_environment_snapshot.sh" results/snapshot.json
)
jq -e --arg value "$value" '
  .schema_version == 1 and .stage == "run" and .system.name == "TestSystem" and
  .execution.activity == $value and .toolchain.environment.CFLAGS == $value and
  .toolchain.environment.SECRET_TOKEN == "[redacted]" and
  (.toolchain.environment | keys | length) == 2 and
  (.toolchain.commands | keys) == ["bash"] and
  (.toolchain.commands.bash.sha256 | test("^[0-9a-f]{64}$")) and
  .toolchain.python3 == "" and .toolchain.modules == ["compiler/test", "mpi/test"]
' "$TMP_DIR/work/results/snapshot.json" >/dev/null
if grep -q 'never-publish-this' "$TMP_DIR/work/results/snapshot.json"; then
  echo 'Snapshot exposed a redacted value' >&2
  exit 1
fi

# Build-tool interception must use the same dependency-free collector.
for fallback in false true; do
  PATH="$restricted_path" BK_BENCHKIT_ROOT="$REPO_DIR" \
    BK_BUILD_TOOL_WRAPPER_FORCE_FALLBACK="$fallback" \
    BK_BUILD_ENVIRONMENT_SNAPSHOT_FILE="$TMP_DIR/build.json" \
    bash "$REPO_DIR/scripts/build_tool_wrappers/bk_build_tool_wrapper.sh" bash -c 'exit 0'
  jq -e --arg value "$value" '.stage == "build_actual" and
    .toolchain.environment.CFLAGS == $value and
    .toolchain.environment.SECRET_TOKEN == "[redacted]"' "$TMP_DIR/build.json" >/dev/null
done

PATH="$restricted_path" CI_JOB_STARTED_AT='2026-01-02T03:04:05Z' \
  bash "$REPO_DIR/scripts/record_ci_timing_context.sh" run "$TMP_DIR/timing.json"
jq -e '.stage == "run" and (.ci_job_started_epoch | type) == "number" and
  .ci_job_started_at_source == "CI_JOB_STARTED_AT"' "$TMP_DIR/timing.json" >/dev/null

PATH="$restricted_path" CI_JOB_STARTED_AT='invalid timestamp' \
  bash "$REPO_DIR/scripts/record_ci_timing_context.sh" run "$TMP_DIR/timing.json"
jq -e '.ci_job_started_at == "invalid timestamp" and
  (has("ci_job_started_epoch") | not)' "$TMP_DIR/timing.json" >/dev/null
PATH="$restricted_path" BK_NODE_STATUS_SNAPSHOT_REMOTE=0 \
  bash "$REPO_DIR/scripts/collect_node_status_snapshot.sh" "$TMP_DIR/node.json"
test -s "$TMP_DIR/node.json.capture"
bash "$REPO_DIR/scripts/result_server/finalize_node_status_snapshot.sh" "$TMP_DIR/node.json"
jq -e '.summary.observed_host_count == 1 and
  .observed.hosts[0].gpu_state.query_status == "unavailable" and
  (has("record_format") | not)' "$TMP_DIR/node.json" >/dev/null
echo 'Compute snapshot dependency tests passed'
