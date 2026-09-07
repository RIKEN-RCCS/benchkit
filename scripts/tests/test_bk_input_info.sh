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
