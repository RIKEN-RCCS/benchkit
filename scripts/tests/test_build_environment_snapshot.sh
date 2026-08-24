#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping build environment snapshot test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/project/scripts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/src" "${TMP_DIR}/bin"
cp "${REPO_DIR}/scripts/bk_functions.sh" "${TMP_DIR}/project/scripts/bk_functions.sh"
cp "${REPO_DIR}/scripts/collect_environment_snapshot.sh" "${TMP_DIR}/project/scripts/collect_environment_snapshot.sh"
cp "${REPO_DIR}/scripts/result.sh" "${TMP_DIR}/project/scripts/result.sh"
cp -R "${REPO_DIR}/scripts/build_tool_wrappers" "${TMP_DIR}/project/scripts/build_tool_wrappers"

cat > "${TMP_DIR}/project/results/result" <<'EOF'
FOM:1.0 FOM_unit:s FOM_version:test Exp:CASE0 node_count:1 numproc_node:1 nthreads:1
EOF

cat > "${TMP_DIR}/project/results/environment_snapshot_build.json" <<'EOF'
{
  "schema_version": 1,
  "stage": "build",
  "collected_at": "2026-08-24T00:00:00Z",
  "system": {
    "name": "TestSystem",
    "allocation_project_id": ""
  },
  "scheduler": {
    "kind": "unknown"
  },
  "runner": {
    "description": "test-runner"
  },
  "ci": {},
  "benchkit": {},
  "toolchain": {
    "modules": []
  }
}
EOF

cat > "${TMP_DIR}/bin/make" <<'EOF'
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" > "${BK_TEST_FAKE_MAKE_ARGS}"
EOF
chmod +x "${TMP_DIR}/bin/make"

pushd "${TMP_DIR}/project/src" >/dev/null
export BK_SYSTEM=TestSystem
export BK_BENCHKIT_ROOT="${TMP_DIR}/project"
export BK_SNAPSHOT_TOOL_COMMANDS="make bash"
export BK_SNAPSHOT_ENV_VARS="CC SECRET_TOKEN"
export PATH="${TMP_DIR}/project/scripts/build_tool_wrappers:${TMP_DIR}/bin:${PATH}"
export CC=mpicc
export SECRET_TOKEN=should_not_be_recorded
export BK_TEST_FAKE_MAKE_ARGS="${TMP_DIR}/make_args"
make -j2 target
popd >/dev/null

SNAPSHOT="${TMP_DIR}/project/results/environment_snapshot_build_actual.json"
test -f "$SNAPSHOT"
test "$(cat "${TMP_DIR}/make_args")" = "-j2 target"
jq -e --arg make_path "${TMP_DIR}/bin/make" '
  .stage == "build_actual" and
  .system.name == "TestSystem" and
  .toolchain.commands.make.path == $make_path and
  (.toolchain.commands.bash.path | length) > 0 and
  .toolchain.environment.CC == "mpicc" and
  .toolchain.environment.SECRET_TOKEN == "[redacted]"
' "$SNAPSHOT" >/dev/null

pushd "${TMP_DIR}/project" >/dev/null
bash scripts/result.sh app TestSystem native build run 123 >/dev/null
popd >/dev/null

jq -e '
  .environment_snapshot.payload.stages.build.stage == "build" and
  .environment_snapshot.payload.stages.build_actual.stage == "build_actual" and
  .environment_snapshot.payload.toolchain.build_actual.environment.CC == "mpicc" and
  (.environment_snapshot.hash | startswith("sha256:"))
' "${TMP_DIR}/project/results/result0.json" >/dev/null

rm -f "${TMP_DIR}/project/results/environment_snapshot_build_actual.json" "${TMP_DIR}/project/results/result0.json"
pushd "${TMP_DIR}/project/src" >/dev/null
export BK_BUILD_TOOL_WRAPPER_FORCE_FALLBACK=true
export BK_TEST_FAKE_MAKE_ARGS="${TMP_DIR}/make_args_fallback"
make fallback
unset BK_BUILD_TOOL_WRAPPER_FORCE_FALLBACK
popd >/dev/null

test -f "$SNAPSHOT"
test "$(cat "${TMP_DIR}/make_args_fallback")" = "fallback"
jq -e --arg make_path "${TMP_DIR}/bin/make" '
  .stage == "build_actual" and
  .system.name == "TestSystem" and
  .toolchain.commands.make.path == $make_path and
  .toolchain.environment.CC == "mpicc" and
  .toolchain.environment.SECRET_TOKEN == "[redacted]"
' "$SNAPSHOT" >/dev/null

pushd "${TMP_DIR}/project" >/dev/null
bash scripts/result.sh app TestSystem native build run 123 >/dev/null
popd >/dev/null

jq -e '
  .environment_snapshot.payload.stages.build_actual.stage == "build_actual" and
  .environment_snapshot.payload.toolchain.build_actual.environment.CC == "mpicc" and
  (.environment_snapshot.hash | startswith("sha256:"))
' "${TMP_DIR}/project/results/result0.json" >/dev/null

echo "build environment snapshot test passed"
