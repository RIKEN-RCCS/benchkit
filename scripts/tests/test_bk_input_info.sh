#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

source "${REPO_DIR}/scripts/bk_functions.sh"

pushd "${TMP_DIR}" >/dev/null

bk_record_input_info <<'EOF'
{
  "schema_version": 1,
  "inputs": [
    {
      "dataset_id": "demo-case0",
      "verification_status": "declared"
    }
  ]
}
EOF

test -s results/input_info.json
if command -v jq >/dev/null 2>&1; then
  jq -e '.inputs[0].dataset_id == "demo-case0"' results/input_info.json >/dev/null
fi

mkdir -p metadata
cat > metadata/input_info.json <<'EOF'
{
  "schema_version": 1,
  "inputs": [
    {
      "dataset_id": "demo-case1",
      "verification_status": "declared"
    }
  ]
}
EOF

BK_INPUT_INFO_FILE=custom/input_info.json bk_record_input_info metadata/input_info.json
test -s custom/input_info.json
if command -v jq >/dev/null 2>&1; then
  jq -e '.inputs[0].dataset_id == "demo-case1"' custom/input_info.json >/dev/null
fi

rm -f results/input_info.json results/.input_info_items.jsonl
bk_record_input \
  --dataset-id demo-case0-parameters \
  --dataset-version v1 \
  --parameter-set-id CASE0 \
  --result-exp CASE0 \
  --command ./main \
  --recipe "run ./main with recorded arguments" \
  -- 32 6 4 3 1 1 1 1 -1 -1 6 50
bk_record_input \
  --dataset-id demo-case1-parameters \
  --parameter-set-id CASE1 \
  --result-exp CASE1 \
  --command ./main \
  -- 32 6 4 3 1 1 1 2 -1 -1 6 50
test -s results/input_info.json
if command -v jq >/dev/null 2>&1; then
  jq -e '
    .schema_version == 1 and
    (.inputs | length) == 2 and
    .inputs[0].dataset_id == "demo-case0-parameters" and
    .inputs[0].dataset_version == "v1" and
    .inputs[0].kind == "runtime-parameters" and
    .inputs[0].source == "inline" and
    .inputs[0].parameter_set_id == "CASE0" and
    .inputs[0].result_exp == "CASE0" and
    .inputs[0].command == "./main" and
    .inputs[0].arguments == ["32", "6", "4", "3", "1", "1", "1", "1", "-1", "-1", "6", "50"] and
    .inputs[0].verification_status == "self_contained" and
    .inputs[1].parameter_set_id == "CASE1"
  ' results/input_info.json >/dev/null
fi

bk_reset_input_info
bk_record_input \
  --dataset-id demo-prestaged-input \
  --version v2 \
  --type file \
  --result-exp CASE0 \
  --parameter restart 100 \
  --recipe "declared pre-staged benchmark input"
bk_record_input \
  --dataset-id demo-source-config \
  --result-exp CASE0 \
  --path test/case0 \
  --recipe "configuration covered by source provenance"
bk_record_input \
  --dataset-id demo-source-input \
  --repo-url https://example.org/input.git \
  --ref main \
  --commit 1234567890abcdef1234567890abcdef12345678 \
  --path input/case0 \
  --parameter case CASE0 \
  --recipe "input fixed by source commit with runtime selector" \
  --command ./prepare-input \
  -- --case CASE0
bk_record_input \
  --parameter-set-id CASE2 \
  --result-exp CASE2 \
  --parameter size small \
  --parameter iterations 10
test -s results/input_info.json
if command -v jq >/dev/null 2>&1; then
  jq -e '
    .schema_version == 1 and
    (.inputs | length) == 4 and
    .inputs[0].dataset_id == "demo-prestaged-input" and
    .inputs[0].dataset_version == "v2" and
    .inputs[0].kind == "pre-staged-file" and
    .inputs[0].source == "site-local" and
    .inputs[0].parameters.restart == "100" and
    .inputs[0].verification_status == "declared" and
    .inputs[1].dataset_id == "demo-source-config" and
    .inputs[1].kind == "repo-local-input" and
    .inputs[1].source == "source_info" and
    .inputs[1].repo_relative_path == "test/case0" and
    .inputs[1].verification_status == "covered_by_source_commit" and
    .inputs[2].dataset_id == "demo-source-input" and
    .inputs[2].kind == "git-repository" and
    .inputs[2].source == "source_url" and
    .inputs[2].source_url == "https://example.org/input.git" and
    .inputs[2].source_ref == "main" and
    .inputs[2].resolved_commit == "1234567890abcdef1234567890abcdef12345678" and
    .inputs[2].repo_relative_path == "input/case0" and
    .inputs[2].parameters.case == "CASE0" and
    .inputs[2].command == "./prepare-input" and
    .inputs[2].arguments == ["--case", "CASE0"] and
    .inputs[2].verification_status == "source_commit" and
    .inputs[3].dataset_id == "runtime-parameters-CASE2" and
    .inputs[3].kind == "inline-parameters" and
    .inputs[3].source == "inline" and
    .inputs[3].parameter_set_id == "CASE2" and
    .inputs[3].parameters.size == "small" and
    .inputs[3].parameters.iterations == "10" and
    .inputs[3].verification_status == "self_contained"
  ' results/input_info.json >/dev/null
fi

bk_reset_input_info
test ! -e results/input_info.json
test ! -e results/.input_info_items.jsonl

# Synthetic inputs exercise the contract without pinning application datasets.
input_sha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
printf abc > 'private input.bin'
input_path="${TMP_DIR}/private input.bin"
bk_record_input --dataset-id demo-verified --version v1 --type file \
  --result-exp CASE0 --verify-file "$input_path" \
  --expected-sha256 "${input_sha256^^}" --expected-size-bytes 3
if command -v jq >/dev/null 2>&1; then
  jq -e --arg sha "$input_sha256" '
    .inputs[0].verification_status == "verified" and
    .inputs[0].sha256 == $sha and .inputs[0].size_bytes == 3 and
    .inputs[0].result_exp == "CASE0" and
    (.inputs[0] | has("repo_relative_path") | not)
  ' results/input_info.json >/dev/null
fi
cp results/input_info.json expected-info.json
cp results/.input_info_items.jsonl expected-items.jsonl

reject_verification() {
  if bk_record_input --dataset-id demo-invalid "$@" > verification.out 2> verification.err; then
    echo "bk_record_input accepted invalid file verification" >&2
    exit 1
  fi
  cmp results/input_info.json expected-info.json
  cmp results/.input_info_items.jsonl expected-items.jsonl
  test ! -s verification.out
  if grep -F -e "$TMP_DIR" -e 'private input.bin' verification.err; then
    echo "bk_record_input exposed an input location" >&2
    exit 1
  fi
}

reject_verification --type file --verify-file "$input_path"
reject_verification --type file --expected-sha256 "$input_sha256" --expected-size-bytes 3
reject_verification --type file --verify-file "$input_path" --expected-sha256 '' --expected-size-bytes 3
reject_verification --type file --verify-file "$input_path" --expected-sha256 invalid --expected-size-bytes 3
reject_verification --type file --verify-file "$input_path" --expected-sha256
for size in '' -1 03 3.0 nope 4; do
  reject_verification --type file --verify-file "$input_path" \
    --expected-sha256 "$input_sha256" --expected-size-bytes "$size"
done
for path in "$TMP_DIR/missing" "$TMP_DIR"; do
  reject_verification --type file --verify-file "$path" \
    --expected-sha256 "$input_sha256" --expected-size-bytes 3
done
mkfifo input-pipe
reject_verification --type file --verify-file input-pipe \
  --expected-sha256 "$input_sha256" --expected-size-bytes 3
reject_verification --type restart --verify-file "$input_path" \
  --expected-sha256 "$input_sha256" --expected-size-bytes 3
# A same-size replacement must not be accepted using cached metadata.
printf abd > "$input_path"
reject_verification --type file --verify-file "$input_path" \
  --expected-sha256 "$input_sha256" --expected-size-bytes 3
printf abc > "$input_path"
(
  bk_sha256_file() { return 1; }
  reject_verification --type file --verify-file "$input_path" \
    --expected-sha256 "$input_sha256" --expected-size-bytes 3
)
(
  bk_sha256_file() { printf '%s\n' "$input_sha256"; return 1; }
  reject_verification --type file --verify-file "$input_path" \
    --expected-sha256 "$input_sha256" --expected-size-bytes 3
)

# Symlinks are permitted, but the target bytes are verified on every call.
ln -s "$input_path" input-link
bk_record_input --dataset-id demo-link --type matrix --verify-file input-link \
  --expected-sha256 "$input_sha256" --expected-size-bytes 3
printf '' > empty-input
bk_record_input --dataset-id demo-empty --type file --verify-file empty-input \
  --expected-sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 \
  --expected-size-bytes 0
# Existing declared calls must not inherit verification from a preceding call.
bk_record_input --dataset-id demo-declared --type file
if command -v jq >/dev/null 2>&1; then
  jq -e '
    (.inputs | length) == 4 and
    .inputs[1].verification_status == "verified" and
    .inputs[2].size_bytes == 0 and
    .inputs[3].verification_status == "declared" and
    (.inputs[3] | has("sha256") or has("size_bytes") | not)
  ' results/input_info.json >/dev/null
fi
if grep -F "$input_path" results/input_info.json; then
  echo "bk_record_input stored an input location" >&2
  exit 1
fi

bk_write_source_info_env \
  git \
  "https://example.test/demo.git" \
  main \
  1234567890abcdef1234567890abcdef12345678 \
  "" "" "" "" "" \
  main \
  branch \
  1234567890abcdef1234567890abcdef12345678
test "$(bk_env_file_value results/source_info.env BK_REPO_URL)" = "https://example.test/demo.git"
test "$(bk_env_file_value results/source_info.env BK_SOURCE_RESOLVED_COMMIT)" = "1234567890abcdef1234567890abcdef12345678"

if bk_record_input_info missing.json >/dev/null 2>&1; then
  echo "bk_record_input_info accepted a missing file" >&2
  exit 1
fi

if printf '' | bk_record_input_info >/dev/null 2>&1; then
  echo "bk_record_input_info accepted empty input" >&2
  exit 1
fi

if command -v jq >/dev/null 2>&1; then
  if printf '[]' | bk_record_input_info >/dev/null 2>&1; then
    echo "bk_record_input_info accepted a non-object JSON value" >&2
    exit 1
  fi
fi

popd >/dev/null

echo "bk_record_input_info test passed"
