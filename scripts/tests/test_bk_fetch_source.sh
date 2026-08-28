#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping bk_fetch_source test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

source "${REPO_DIR}/scripts/bk_functions.sh"

write_minimal_result() {
  mkdir -p results
  cat > results/result <<'EOF'
FOM:1.0 FOM_unit:s FOM_version:test Exp:CASE0 node_count:1 numproc_node:1 nthreads:1
EOF
}

make_zero_sha1() {
  printf '0%.0s' {1..40}
}

make_zero_sha256() {
  printf '0%.0s' {1..64}
}

mkdir -p "${TMP_DIR}/src"
git -C "${TMP_DIR}/src" init -q
git -C "${TMP_DIR}/src" config user.email "benchkit-test@example.invalid"
git -C "${TMP_DIR}/src" config user.name "Benchkit Test"
git -C "${TMP_DIR}/src" checkout -q -b main
printf 'first\n' > "${TMP_DIR}/src/value.txt"
git -C "${TMP_DIR}/src" add value.txt
git -C "${TMP_DIR}/src" commit -q -m "first"
commit_one=$(git -C "${TMP_DIR}/src" rev-parse HEAD)
git -C "${TMP_DIR}/src" tag -a v1.0 -m "version one" "$commit_one"
printf 'second\n' > "${TMP_DIR}/src/value.txt"
git -C "${TMP_DIR}/src" commit -q -am "second"
git -C "${TMP_DIR}/src" clone -q --bare "${TMP_DIR}/src" "${TMP_DIR}/origin.git"

mkdir -p "${TMP_DIR}/git-work"
pushd "${TMP_DIR}/git-work" >/dev/null
write_minimal_result
bk_fetch_source "${TMP_DIR}/origin.git" checkout main "$commit_one"
test "$(git -C checkout rev-parse HEAD)" = "$commit_one"
bash "${REPO_DIR}/scripts/result.sh" app TestSystem native build run 123 >/dev/null
jq -e --arg commit "$commit_one" '
  .source_info.source_type == "git" and
  .source_info.branch == "main" and
  .source_info.commit_hash == $commit and
  .source_info.ref_name == "main" and
  .source_info.ref_kind == "branch" and
  .source_info.resolved_commit == $commit
' results/result0.json >/dev/null
popd >/dev/null

mkdir -p "${TMP_DIR}/git-tag-work"
pushd "${TMP_DIR}/git-tag-work" >/dev/null
write_minimal_result
bk_fetch_source "${TMP_DIR}/origin.git" checkout v1.0
test "$(git -C checkout rev-parse HEAD)" = "$commit_one"
bash "${REPO_DIR}/scripts/result.sh" app TestSystem native build run 123 >/dev/null
jq -e --arg commit "$commit_one" '
  .source_info.source_type == "git" and
  .source_info.branch == "v1.0" and
  .source_info.commit_hash == $commit and
  .source_info.ref_name == "v1.0" and
  .source_info.ref_kind == "tag" and
  .source_info.resolved_commit == $commit
' results/result0.json >/dev/null
popd >/dev/null

mkdir -p "${TMP_DIR}/git-mismatch"
pushd "${TMP_DIR}/git-mismatch" >/dev/null
write_minimal_result
if bk_fetch_source "${TMP_DIR}/origin.git" checkout main "$(make_zero_sha1)" >/dev/null 2>&1; then
  echo "bk_fetch_source accepted a mismatched git commit" >&2
  exit 1
fi
popd >/dev/null

mkdir -p "${TMP_DIR}/archive-src/payload"
printf 'archive payload\n' > "${TMP_DIR}/archive-src/payload/value.txt"
tar -czf "${TMP_DIR}/source.tar.gz" -C "${TMP_DIR}/archive-src" payload
archive_sha256=$(bk_sha256_file "${TMP_DIR}/source.tar.gz")

mkdir -p "${TMP_DIR}/archive-work"
pushd "${TMP_DIR}/archive-work" >/dev/null
write_minimal_result
bk_fetch_source "${TMP_DIR}/source.tar.gz" payload "" "$archive_sha256"
test -f payload/value.txt
bash "${REPO_DIR}/scripts/result.sh" app TestSystem native build run 123 >/dev/null
jq -e --arg sha256 "$archive_sha256" '
  .source_info.source_type == "file" and
  .source_info.sha256sum == $sha256 and
  (.source_info.md5sum | length) == 32
' results/result0.json >/dev/null
popd >/dev/null

mkdir -p "${TMP_DIR}/archive-mismatch"
pushd "${TMP_DIR}/archive-mismatch" >/dev/null
write_minimal_result
if bk_fetch_source "${TMP_DIR}/source.tar.gz" payload "" "$(make_zero_sha256)" >/dev/null 2>&1; then
  echo "bk_fetch_source accepted a mismatched archive sha256" >&2
  exit 1
fi
popd >/dev/null

mkdir -p "${TMP_DIR}/archive-require"
pushd "${TMP_DIR}/archive-require" >/dev/null
write_minimal_result
if BK_REQUIRE_SOURCE_SHA256=true bk_fetch_source "${TMP_DIR}/source.tar.gz" payload >/dev/null 2>&1; then
  echo "bk_fetch_source accepted an unpinned archive with BK_REQUIRE_SOURCE_SHA256=true" >&2
  exit 1
fi
popd >/dev/null

echo "bk_fetch_source provenance verification test passed"
