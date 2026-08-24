#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p \
  "${TMP_DIR}/project/programs/app" \
  "${TMP_DIR}/project/scripts" \
  "${TMP_DIR}/project/scripts/build_tool_wrappers" \
  "${TMP_DIR}/source"

cp "${REPO_DIR}/scripts/bk_functions.sh" "${TMP_DIR}/project/scripts/bk_functions.sh"
cp "${REPO_DIR}/scripts/build_with_cache.sh" "${TMP_DIR}/project/scripts/build_with_cache.sh"
cp "${REPO_DIR}/scripts/collect_environment_snapshot.sh" "${TMP_DIR}/project/scripts/collect_environment_snapshot.sh"
cp "${REPO_DIR}/scripts/matrix_generate.sh" "${TMP_DIR}/project/scripts/matrix_generate.sh"
cp -R "${REPO_DIR}/scripts/build_tool_wrappers" "${TMP_DIR}/project/scripts/"

pushd "${TMP_DIR}/source" >/dev/null
git init --initial-branch=main >/dev/null
git config user.email "benchkit@example.invalid"
git config user.name "Benchkit Test"
printf 'one\n' > source.txt
git add source.txt
git commit -m "first" >/dev/null
first_commit=$(git rev-parse HEAD)
popd >/dev/null

cat > "${TMP_DIR}/project/programs/app/build.sh" <<'EOF'
#!/bin/bash
set -euo pipefail

system="$1"
source scripts/bk_functions.sh
mkdir -p artifacts
bk_fetch_source "${BK_TEST_SOURCE_REPO}" appsrc main

count=0
if [ -f "${BK_TEST_BUILD_COUNT}" ]; then
  count=$(cat "${BK_TEST_BUILD_COUNT}")
fi
count=$((count + 1))
printf '%s\n' "$count" > "${BK_TEST_BUILD_COUNT}"
printf 'artifact %s %s\n' "$system" "$BK_COMMIT_HASH" > artifacts/app.bin
EOF
chmod +x "${TMP_DIR}/project/programs/app/build.sh"

app_build_hash=$(sha256sum "${TMP_DIR}/project/programs/app/build.sh" | awk '{print $1}')

run_build_with_cache_for_root() {
  local project_root="$1"

  pushd "$project_root" >/dev/null
  BK_BENCHKIT_ROOT="$project_root" \
    BK_BUILD_CACHE_DIR="${TMP_DIR}/cache" \
    BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE=true \
    BK_BUILD_CACHE_ENV_KEY=test-toolchain-v1 \
    BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
    BK_TEST_BUILD_COUNT="${TMP_DIR}/build-count" \
    bash scripts/build_with_cache.sh app TestSystem programs/app
  popd >/dev/null
}

run_build_with_cache() {
  run_build_with_cache_for_root "${TMP_DIR}/project"
}

run_build_without_host_restore_opt_in_for_root() {
  local project_root="$1"

  pushd "$project_root" >/dev/null
  BK_BENCHKIT_ROOT="$project_root" \
    BK_BUILD_CACHE_DIR="${TMP_DIR}/cache" \
    BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
    BK_TEST_BUILD_COUNT="${TMP_DIR}/build-count" \
    bash scripts/build_with_cache.sh app TestSystem programs/app
  popd >/dev/null
}

run_build_without_host_restore_opt_in() {
  run_build_without_host_restore_opt_in_for_root "${TMP_DIR}/project"
}

run_build_with_cache
test "$(cat "${TMP_DIR}/build-count")" = "1"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"
test -f "${TMP_DIR}/cache/app/TestSystem/manifest.env"
grep -q "$app_build_hash" "${TMP_DIR}/cache/app/TestSystem/manifest.env" && {
  echo "build cache manifest should contain only aggregate hashes, not raw file hashes" >&2
  exit 1
}

cp -a "${TMP_DIR}/project" "${TMP_DIR}/project-copy"
rm -rf "${TMP_DIR}/project-copy/artifacts" "${TMP_DIR}/project-copy/results" "${TMP_DIR}/project-copy/appsrc"
run_build_with_cache_for_root "${TMP_DIR}/project-copy"
test "$(cat "${TMP_DIR}/build-count")" = "1"
grep -q "$first_commit" "${TMP_DIR}/project-copy/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STATUS=hit$' "${TMP_DIR}/project-copy/results/build_cache.env"

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_build_without_host_restore_opt_in
test "$(cat "${TMP_DIR}/build-count")" = "2"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STATUS=miss$' "${TMP_DIR}/project/results/build_cache.env"
grep -q '^BK_BUILD_CACHE_STORED=false$' "${TMP_DIR}/project/results/build_cache.env"

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_build_with_cache
test "$(cat "${TMP_DIR}/build-count")" = "2"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STATUS=hit$' "${TMP_DIR}/project/results/build_cache.env"

pushd "${TMP_DIR}/source" >/dev/null
printf 'two\n' > source.txt
git add source.txt
git commit -m "second" >/dev/null
second_commit=$(git rev-parse HEAD)
popd >/dev/null

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_build_with_cache
test "$(cat "${TMP_DIR}/build-count")" = "3"
grep -q "$second_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"

printf '\n# build input change\n' >> "${TMP_DIR}/project/programs/app/build.sh"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_build_with_cache
test "$(cat "${TMP_DIR}/build-count")" = "4"
grep -q "$second_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"

echo "build cache test passed"
