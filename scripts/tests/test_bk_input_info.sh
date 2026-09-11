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
bk_record_runtime_parameter_input \
  --dataset-id demo-case0-parameters \
  --dataset-version v1 \
  --parameter-set-id CASE0 \
  --result-exp CASE0 \
  --command ./main \
  --recipe "run ./main with recorded arguments" \
  -- 32 6 4 3 1 1 1 1 -1 -1 6 50
bk_record_runtime_parameter_input \
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
