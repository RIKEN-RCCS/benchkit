#!/bin/bash
set -euo pipefail

# shellcheck disable=SC1091,SC2034,SC2154

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping estimation common JSON contract test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/scripts" "${TMP_DIR}/results"
cp -R "${REPO_DIR}/scripts/estimation" "${TMP_DIR}/scripts/estimation"
cp -R "${REPO_DIR}/scripts/result_server" "${TMP_DIR}/scripts/result_server"

pushd "${TMP_DIR}" >/dev/null

source scripts/estimation/common.sh

cat > results/source_result.json <<'JSON'
{
  "code": "contractapp",
  "Exp": "case0",
  "system": "SourceSystem",
  "FOM": 5.0,
  "node_count": 2,
  "numproc_node": 4,
  "_server_uuid": "11111111-2222-3333-4444-555555555555",
  "_server_timestamp": "20260907_100000",
  "input_info": {
    "schema_version": 1,
    "inputs": [
      {
        "dataset_id": "contract-case0",
        "kind": "repo-local-input",
        "verification_status": "covered_by_source_commit"
      }
    ]
  }
}
JSON

read_values results/source_result.json

est_current_system="$est_system"
est_current_fom="$est_fom"
est_current_target_nodes="$est_node_count"
est_current_scaling_method="identity"
est_current_bench_system="$est_system"
est_current_bench_fom="$est_fom"
est_current_bench_nodes="$est_node_count"
est_current_bench_numproc_node="$est_numproc_node"
est_current_bench_timestamp="$est_timestamp"
est_current_bench_uuid="$est_uuid"

est_future_system="FutureSystem"
est_future_fom="2.5"
est_future_target_nodes="$est_node_count"
est_future_scaling_method="identity"
est_future_bench_system="$est_system"
est_future_bench_fom="$est_fom"
est_future_bench_nodes="$est_node_count"
est_future_bench_numproc_node="$est_numproc_node"
est_future_bench_timestamp="$est_timestamp"
est_future_bench_uuid="$est_uuid"

print_json > results/estimate_common_contract.json

jq -e '
  type == "object" and
  .code == "contractapp" and
  .exp == "case0" and
  (.current_system | type) == "object" and
  (.future_system | type) == "object" and
  .current_system.system == "SourceSystem" and
  .future_system.system == "FutureSystem" and
  .performance_ratio == 2 and
  (.estimate_metadata | type) == "object" and
  (.estimate_metadata.source_result | type) == "object" and
  .estimate_metadata.source_result.uuid == "11111111-2222-3333-4444-555555555555" and
  .estimate_metadata.source_result.timestamp == "2026-09-07 10:00:00" and
  .estimate_metadata.source_result.code == "contractapp" and
  .estimate_metadata.source_result.exp == "case0" and
  .estimate_metadata.source_result.system == "SourceSystem" and
  .estimate_metadata.source_result.node_count == "2" and
  .estimate_metadata.source_result.numproc_node == "4" and
  .estimate_metadata.source_result.input_info.schema_version == 1 and
  .estimate_metadata.source_result.input_info.inputs[0].dataset_id == "contract-case0" and
  (.estimate_metadata.current_source_result | type) == "object" and
  .estimate_metadata.current_source_result.system == "SourceSystem" and
  (.estimate_metadata.future_source_result | type) == "object" and
  .estimate_metadata.future_source_result.system == "SourceSystem"
' results/estimate_common_contract.json >/dev/null

popd >/dev/null

echo "estimation common JSON contract test passed"
