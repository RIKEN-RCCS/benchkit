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
cp "${REPO_DIR}/scripts/bk_build.sh" "${TMP_DIR}/project/scripts/bk_build.sh"
cp -R "${REPO_DIR}/scripts/common" "${TMP_DIR}/project/scripts/common"
mkdir -p "${TMP_DIR}/project/scripts/estimation"
cp "${REPO_DIR}/scripts/estimation/declaration_helpers.sh" "${TMP_DIR}/project/scripts/estimation/"
cp -R "${REPO_DIR}/scripts/profiling" "${TMP_DIR}/project/scripts/"
cp "${REPO_DIR}/scripts/collect_environment_snapshot.sh" "${TMP_DIR}/project/scripts/collect_environment_snapshot.sh"
cp "${REPO_DIR}/scripts/json_output.sh" "${TMP_DIR}/project/scripts/json_output.sh"
cp "${REPO_DIR}/scripts/result.sh" "${TMP_DIR}/project/scripts/result.sh"
mkdir -p "${TMP_DIR}/project/scripts/result_server"
cp "${REPO_DIR}/scripts/result_server/"{input_info.sh,input_manifest.jq,workflow_timing.sh} \
  "${TMP_DIR}/project/scripts/result_server/"
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

cat > "${TMP_DIR}/bin/nvcc" <<'EOF'
#!/bin/bash
set -euo pipefail
if [ "${1:-}" != "-V" ]; then
  echo "unexpected nvcc version argument: ${1:-}" >&2
  exit 2
fi
cat <<'OUT'
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2025 NVIDIA Corporation
Built on Tue_Dec_16_07:27:17_PM_PST_2025
Cuda compilation tools, release 13.1, V13.1.115
Build cuda_13.1.r13.1/compiler.37061995_0
OUT
EOF
chmod +x "${TMP_DIR}/bin/nvcc"

cat > "${TMP_DIR}/bin/nvc" <<'EOF'
#!/bin/bash
set -euo pipefail
if [ "${1:-}" != "-V" ]; then
  echo "unexpected nvc version argument: ${1:-}" >&2
  exit 2
fi
cat <<'OUT'

nvc 26.3-0 linuxarm64 target on aarch64 Linux -tp neoverse-v2
NVIDIA Compilers and Tools
Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.  All rights reserved.
OUT
EOF
chmod +x "${TMP_DIR}/bin/nvc"

pushd "${TMP_DIR}/project/src" >/dev/null
export BK_SYSTEM=TestSystem
export BK_EXECUTION_ACTIVITY=ActivityAlpha
export BK_BENCHKIT_ROOT="${TMP_DIR}/project"
export BK_SNAPSHOT_TOOL_COMMANDS="make bash nvcc nvc"
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
jq -e \
  --arg make_path "${TMP_DIR}/bin/make" \
  --arg nvcc_path "${TMP_DIR}/bin/nvcc" \
  --arg nvc_path "${TMP_DIR}/bin/nvc" \
  '
  .stage == "build_actual" and
  .system.name == "TestSystem" and
  .execution.activity == "ActivityAlpha" and
  .toolchain.commands.make.path == $make_path and
  (.toolchain.commands.bash.path | length) > 0 and
  .toolchain.nvcc == "Cuda compilation tools, release 13.1, V13.1.115" and
  .toolchain.commands.nvcc.path == $nvcc_path and
  .toolchain.commands.nvcc.version == "Cuda compilation tools, release 13.1, V13.1.115" and
  .toolchain.commands.nvc.path == $nvc_path and
  .toolchain.commands.nvc.version == "nvc 26.3-0 linuxarm64 target on aarch64 Linux -tp neoverse-v2" and
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
jq -e \
  --arg make_path "${TMP_DIR}/bin/make" \
  --arg nvcc_path "${TMP_DIR}/bin/nvcc" \
  --arg nvc_path "${TMP_DIR}/bin/nvc" \
  '
  .stage == "build_actual" and
  .system.name == "TestSystem" and
  .toolchain.commands.make.path == $make_path and
  .toolchain.nvcc == "Cuda compilation tools, release 13.1, V13.1.115" and
  .toolchain.commands.nvcc.path == $nvcc_path and
  .toolchain.commands.nvcc.version == "Cuda compilation tools, release 13.1, V13.1.115" and
  .toolchain.commands.nvc.path == $nvc_path and
  .toolchain.commands.nvc.version == "nvc 26.3-0 linuxarm64 target on aarch64 Linux -tp neoverse-v2" and
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

# Exercise the default command set in both collectors: an explicit override
# would conceal a missing compiler in the default discovery list.
for compiler in mpiicx mpiicpx mpiifx; do
  cat > "${TMP_DIR}/bin/${compiler}" <<'EOF'
#!/bin/bash
if [ "${1:-}" != "--version" ]; then exit 2; fi
printf '%s version 2026.1\n' "${0##*/}"
EOF
  chmod +x "${TMP_DIR}/bin/${compiler}"
done
for compiler in CC ftn flang amdclang amdclang++ amdflang mpic++ mpiclang mpiclang++ site-cxx site-fc 'compiler space'; do
  cat > "${TMP_DIR}/bin/${compiler}" <<'EOF'
#!/bin/bash
if [ "${1:-}" != "--version" ]; then exit 2; fi
printf '%s version test\n' "${0##*/}"
EOF
  chmod +x "${TMP_DIR}/bin/${compiler}"
done
export CC="\"${TMP_DIR}/bin/compiler space\" -O3"
export CXX='ccache site-cxx -g'
export FC='site-fc -O2'
export F77='$(touch should-not-exist)'
export F90='site-fc; touch should-not-exist'
unset BK_SNAPSHOT_TOOL_COMMANDS
for collector in normal fallback; do
  rm -f "$SNAPSHOT"
  pushd "${TMP_DIR}/project/src" >/dev/null
  BK_BUILD_TOOL_WRAPPER_FORCE_FALLBACK=$([ "$collector" = fallback ] && echo true || echo false) make intel-mpi
  popd >/dev/null
  jq -e --arg path "${TMP_DIR}/bin/compiler space" '
    .toolchain.commands[$path].path == $path and
    .toolchain.commands[$path].version == "compiler space version test" and
    (.toolchain.commands[$path].sha256 | test("^[0-9a-f]{64}$")) and
    .toolchain.commands["site-cxx"].version == "site-cxx version test" and
    .toolchain.commands["site-fc"].version == "site-fc version test"
  ' "$SNAPSHOT" >/dev/null
  for compiler in CC ftn flang amdclang amdclang++ amdflang mpic++ mpiclang mpiclang++; do
    jq -e --arg compiler "$compiler" --arg path "${TMP_DIR}/bin/${compiler}" '
      .toolchain.commands[$compiler] |
      .path == $path and .real_path == $path and
      .version == ($compiler + " version test") and
      (.sha256 | test("^[0-9a-f]{64}$"))
    ' "$SNAPSHOT" >/dev/null
  done
  test ! -e "${TMP_DIR}/project/src/should-not-exist"
  for compiler in mpiicx mpiicpx mpiifx; do
    jq -e --arg compiler "$compiler" --arg path "${TMP_DIR}/bin/${compiler}" '
      .toolchain.commands[$compiler] |
      .path == $path and .real_path == $path and
      .version == ($compiler + " version 2026.1") and
      (.sha256 | test("^[0-9a-f]{64}$"))
    ' "$SNAPSHOT" >/dev/null
    expected_hash=$(sha256sum "${TMP_DIR}/bin/${compiler}" | awk '{print $1}')
    jq -e --arg compiler "$compiler" --arg hash "$expected_hash" \
      '.toolchain.commands[$compiler].sha256 == $hash' "$SNAPSHOT" >/dev/null
  done
done

echo "build environment snapshot test passed"
