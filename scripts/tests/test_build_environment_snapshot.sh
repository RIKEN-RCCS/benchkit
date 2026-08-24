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

mkdir -p "${TMP_DIR}/project/scripts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/src"
cp "${REPO_DIR}/scripts/bk_functions.sh" "${TMP_DIR}/project/scripts/bk_functions.sh"
cp "${REPO_DIR}/scripts/collect_environment_snapshot.sh" "${TMP_DIR}/project/scripts/collect_environment_snapshot.sh"
cp "${REPO_DIR}/scripts/result.sh" "${TMP_DIR}/project/scripts/result.sh"

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

pushd "${TMP_DIR}/project" >/dev/null
source scripts/bk_functions.sh
popd >/dev/null

pushd "${TMP_DIR}/project/src" >/dev/null
export BK_SYSTEM=TestSystem
export BK_SNAPSHOT_TOOL_COMMANDS="bash"
export BK_SNAPSHOT_ENV_VARS="CC SECRET_TOKEN"
export CC=mpicc
export SECRET_TOKEN=should_not_be_recorded
bk_capture_build_environment_snapshot
popd >/dev/null

SNAPSHOT="${TMP_DIR}/project/results/environment_snapshot_build_actual.json"
test -f "$SNAPSHOT"
jq -e '
  .stage == "build_actual" and
  .system.name == "TestSystem" and
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

echo "build environment snapshot test passed"
