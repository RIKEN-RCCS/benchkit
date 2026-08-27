#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p \
  "${TMP_DIR}/project/programs/app" \
  "${TMP_DIR}/project/programs/autotoolapp" \
  "${TMP_DIR}/project/programs/tagapp" \
  "${TMP_DIR}/project/programs/toolapp" \
  "${TMP_DIR}/project/scripts" \
  "${TMP_DIR}/project/scripts/build_tool_wrappers" \
  "${TMP_DIR}/source" \
  "${TMP_DIR}/tools"

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
cat > configure <<'EOF'
#!/bin/bash
set -euo pipefail

if ! make configure-probe; then
  echo "configure probe failed" >&2
  exit 1
fi
test -f configure.probe
EOF
chmod +x configure
git add source.txt configure
git commit -m "first" >/dev/null
first_commit=$(git rev-parse HEAD)
git tag -a v1.0 -m "version one" "$first_commit"
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
chmod 755 artifacts/app.bin
EOF
chmod +x "${TMP_DIR}/project/programs/app/build.sh"

cat > "${TMP_DIR}/project/programs/tagapp/build.sh" <<'EOF'
#!/bin/bash
set -euo pipefail

system="$1"
source scripts/bk_functions.sh
mkdir -p artifacts
bk_fetch_source "${BK_TEST_SOURCE_REPO}" tagsrc v1.0

count=0
if [ -f "${BK_TEST_TAG_BUILD_COUNT}" ]; then
  count=$(cat "${BK_TEST_TAG_BUILD_COUNT}")
fi
count=$((count + 1))
printf '%s\n' "$count" > "${BK_TEST_TAG_BUILD_COUNT}"
printf 'tag artifact %s %s\n' "$system" "$BK_COMMIT_HASH" > artifacts/tagapp.bin
EOF
chmod +x "${TMP_DIR}/project/programs/tagapp/build.sh"

cat > "${TMP_DIR}/project/programs/toolapp/build.sh" <<'EOF'
#!/bin/bash
set -euo pipefail

system="$1"
source scripts/bk_functions.sh
mkdir -p artifacts
bk_fetch_source "${BK_TEST_SOURCE_REPO}" toolsrc main
cd toolsrc
make "$system"
EOF
chmod +x "${TMP_DIR}/project/programs/toolapp/build.sh"

cat > "${TMP_DIR}/project/programs/autotoolapp/build.sh" <<'EOF'
#!/bin/bash
set -euo pipefail

system="$1"
source scripts/bk_functions.sh
mkdir -p artifacts
bk_fetch_source "${BK_TEST_SOURCE_REPO}" autosrc main
cd autosrc
./configure
if ! make "$system" > make.log 2>&1; then
  exit 1
fi
EOF
chmod +x "${TMP_DIR}/project/programs/autotoolapp/build.sh"

cat > "${TMP_DIR}/tools/make" <<'EOF'
#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "--version" ]; then
  echo "GNU Make fake-test"
  exit 0
fi

count=0
if [ -f "${BK_TEST_TOOL_BUILD_COUNT}" ]; then
  count=$(cat "${BK_TEST_TOOL_BUILD_COUNT}")
fi
count=$((count + 1))
printf '%s\n' "$count" > "${BK_TEST_TOOL_BUILD_COUNT}"
if [ "${1:-}" = "configure-probe" ]; then
  printf 'ok\n' > configure.probe
  exit 0
fi
artifact="${BK_TEST_TOOL_ARTIFACT:-../artifacts/toolapp.bin}"
mkdir -p "$(dirname "$artifact")"
printf 'tool artifact %s %s\n' "$*" "${BK_COMMIT_HASH:-missing}" > "$artifact"
EOF
chmod +x "${TMP_DIR}/tools/make"

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

run_tag_build_with_cache() {
  pushd "${TMP_DIR}/project" >/dev/null
  BK_BENCHKIT_ROOT="${TMP_DIR}/project" \
    BK_BUILD_CACHE_DIR="${TMP_DIR}/tag-cache" \
    BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE=true \
    BK_BUILD_CACHE_ENV_KEY=test-toolchain-v1 \
    BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
    BK_TEST_TAG_BUILD_COUNT="${TMP_DIR}/tag-build-count" \
    bash scripts/build_with_cache.sh tagapp TestSystem programs/tagapp
  popd >/dev/null
}

run_integrity_build_with_cache() {
  pushd "${TMP_DIR}/project" >/dev/null
  BK_BENCHKIT_ROOT="${TMP_DIR}/project" \
    BK_BUILD_CACHE_DIR="${TMP_DIR}/integrity-cache" \
    BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE=true \
    BK_BUILD_CACHE_ENV_KEY=test-toolchain-v1 \
    BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
    BK_TEST_BUILD_COUNT="${TMP_DIR}/integrity-build-count" \
    bash scripts/build_with_cache.sh app IntegritySystem programs/app
  popd >/dev/null
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

run_tool_build_with_cache_for_root() {
  local project_root="$1"

  pushd "$project_root" >/dev/null
  PATH="${TMP_DIR}/tools:${PATH}" \
    BK_BENCHKIT_ROOT="$project_root" \
    BK_BUILD_CACHE_DIR="${TMP_DIR}/tool-cache" \
    BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
    BK_TEST_TOOL_BUILD_COUNT="${TMP_DIR}/tool-build-count" \
    bash scripts/build_with_cache.sh toolapp TestSystem programs/toolapp
  popd >/dev/null
}

run_tool_build_with_cache() {
  run_tool_build_with_cache_for_root "${TMP_DIR}/project"
}

run_autotool_build_with_cache_for_root() {
  local project_root="$1"

  pushd "$project_root" >/dev/null
  PATH="${TMP_DIR}/tools:${PATH}" \
    BK_BENCHKIT_ROOT="$project_root" \
    BK_BUILD_CACHE_DIR="${TMP_DIR}/autotool-cache" \
    BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
    BK_TEST_TOOL_BUILD_COUNT="${TMP_DIR}/autotool-build-count" \
    BK_TEST_TOOL_ARTIFACT="../artifacts/autotoolapp.bin" \
    bash scripts/build_with_cache.sh autotoolapp TestSystem programs/autotoolapp
  popd >/dev/null
}

run_autotool_build_with_cache() {
  run_autotool_build_with_cache_for_root "${TMP_DIR}/project"
}

pushd "${TMP_DIR}/project" >/dev/null
BK_BENCHKIT_ROOT="${TMP_DIR}/project" \
  BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
  BK_TEST_BUILD_COUNT="${TMP_DIR}/build-count" \
  bash scripts/build_with_cache.sh app TestSystem programs/app
popd >/dev/null
test "$(cat "${TMP_DIR}/build-count")" = "1"
grep -q '^BK_BUILD_CACHE_STATUS=disabled$' "${TMP_DIR}/project/results/build_cache.env"
grep -q '^BK_BUILD_CACHE_STORED=false$' "${TMP_DIR}/project/results/build_cache.env"
test ! -d "${TMP_DIR}/project/.benchkit_build_cache"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
rm -f "${TMP_DIR}/build-count"

pushd "${TMP_DIR}/project" >/dev/null
BK_BENCHKIT_ROOT="${TMP_DIR}/project" \
  CUSTOM_DIR="${TMP_DIR}/custom-runner" \
  CUSTOM_RUNNER_PROJECT_SLUG="benchkit-test" \
  BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE=true \
  BK_BUILD_CACHE_ENV_KEY=test-toolchain-v1 \
  BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
  BK_TEST_BUILD_COUNT="${TMP_DIR}/build-count" \
  bash scripts/build_with_cache.sh app TestSystem programs/app
popd >/dev/null
test "$(cat "${TMP_DIR}/build-count")" = "1"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"
test -f "${TMP_DIR}/custom-runner/build_cache/benchkit-test/app/TestSystem/manifest.env"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"

pushd "${TMP_DIR}/project" >/dev/null
BK_BENCHKIT_ROOT="${TMP_DIR}/project" \
  CUSTOM_DIR="${TMP_DIR}/custom-runner" \
  CUSTOM_RUNNER_PROJECT_SLUG="benchkit-test" \
  BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE=true \
  BK_BUILD_CACHE_ENV_KEY=test-toolchain-v1 \
  BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
  BK_TEST_BUILD_COUNT="${TMP_DIR}/build-count" \
  bash scripts/build_with_cache.sh app TestSystem programs/app
popd >/dev/null
test "$(cat "${TMP_DIR}/build-count")" = "1"
grep -q '^BK_BUILD_CACHE_STATUS=hit$' "${TMP_DIR}/project/results/build_cache.env"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
rm -f "${TMP_DIR}/build-count"

pushd "${TMP_DIR}/project" >/dev/null
BK_BENCHKIT_ROOT="${TMP_DIR}/project" \
  BK_BUILD_CACHE_DIR="relative-cache" \
  BK_TEST_SOURCE_REPO="${TMP_DIR}/source/.git" \
  BK_TEST_BUILD_COUNT="${TMP_DIR}/build-count" \
  bash scripts/build_with_cache.sh app TestSystem programs/app
popd >/dev/null
test "$(cat "${TMP_DIR}/build-count")" = "1"
grep -q '^BK_BUILD_CACHE_STATUS=disabled$' "${TMP_DIR}/project/results/build_cache.env"
test ! -d "${TMP_DIR}/project/relative-cache"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
rm -f "${TMP_DIR}/build-count"

run_build_with_cache
test "$(cat "${TMP_DIR}/build-count")" = "1"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"
test -f "${TMP_DIR}/cache/app/TestSystem/manifest.env"
grep -q "$app_build_hash" "${TMP_DIR}/cache/app/TestSystem/manifest.env" && {
  echo "build cache manifest should contain only aggregate hashes, not raw file hashes" >&2
  exit 1
}

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_integrity_build_with_cache
test "$(cat "${TMP_DIR}/integrity-build-count")" = "1"
integrity_cache_dir="${TMP_DIR}/integrity-cache/app/IntegritySystem"
awk -F= '$1 == "BK_CACHE_SOURCE_INFO_SHA256" && length($2) == 64 {found=1} END {exit(found ? 0 : 1)}' \
  "${integrity_cache_dir}/manifest.env"
awk -F= '$1 == "BK_CACHE_ARTIFACTS_SHA256" && length($2) == 64 {found=1} END {exit(found ? 0 : 1)}' \
  "${integrity_cache_dir}/manifest.env"

chmod 644 "${integrity_cache_dir}/artifacts/app.bin"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_integrity_build_with_cache
test "$(cat "${TMP_DIR}/integrity-build-count")" = "2"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/app.bin"
test -x "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"

printf 'tampered artifact\n' > "${integrity_cache_dir}/artifacts/app.bin"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_integrity_build_with_cache
test "$(cat "${TMP_DIR}/integrity-build-count")" = "3"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"

printf '\n# tampered source info\n' >> "${integrity_cache_dir}/results/source_info.env"
rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
run_integrity_build_with_cache
test "$(cat "${TMP_DIR}/integrity-build-count")" = "4"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/app.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/appsrc"
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

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/tagsrc"
rm -f "${TMP_DIR}/tag-build-count"
run_tag_build_with_cache
test "$(cat "${TMP_DIR}/tag-build-count")" = "1"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/tagapp.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/tagsrc"
run_tag_build_with_cache
test "$(cat "${TMP_DIR}/tag-build-count")" = "1"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/tagapp.bin"
grep -q '^BK_BUILD_CACHE_STATUS=hit$' "${TMP_DIR}/project/results/build_cache.env"

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/toolsrc"
rm -f "${TMP_DIR}/tool-build-count"
run_tool_build_with_cache
test "$(cat "${TMP_DIR}/tool-build-count")" = "1"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/toolapp.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"
test -f "${TMP_DIR}/tool-cache/toolapp/TestSystem/manifest.env"
awk -F= '$1 == "BK_CACHE_HOST_ENV_FINGERPRINT" && length($2) == 64 {found=1} END {exit(found ? 0 : 1)}' \
  "${TMP_DIR}/tool-cache/toolapp/TestSystem/manifest.env"
jq -e '.toolchain.commands.make.sha256 | length == 64' \
  "${TMP_DIR}/project/results/environment_snapshot_build_actual.json" >/dev/null

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/toolsrc"
run_tool_build_with_cache
test "$(cat "${TMP_DIR}/tool-build-count")" = "1"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/toolapp.bin"
grep -q '^BK_BUILD_CACHE_STATUS=hit$' "${TMP_DIR}/project/results/build_cache.env"

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/autosrc"
rm -f "${TMP_DIR}/autotool-build-count"
run_autotool_build_with_cache
test "$(cat "${TMP_DIR}/autotool-build-count")" = "2"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/autotoolapp.bin"
grep -q '^BK_BUILD_CACHE_STORED=true$' "${TMP_DIR}/project/results/build_cache.env"

rm -rf "${TMP_DIR}/project/artifacts" "${TMP_DIR}/project/results" "${TMP_DIR}/project/autosrc"
run_autotool_build_with_cache
test "$(cat "${TMP_DIR}/autotool-build-count")" = "3"
grep -q "$first_commit" "${TMP_DIR}/project/artifacts/autotoolapp.bin"
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
