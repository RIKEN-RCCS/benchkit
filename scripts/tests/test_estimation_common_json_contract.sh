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
cp -R "${REPO_DIR}/scripts/common" "${TMP_DIR}/scripts/common"
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
  "observation_definition": {"version": "old-observation"},
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

BK_APP_ESTIMATION_METHOD_VERSION="new-method"
print_json > results/estimate_common_contract.json

jq -e '
  type == "object" and
  .estimate_metadata.app_estimation_method.version == "new-method" and
  .estimate_metadata.source_result.observation_definition.version == "old-observation" and
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

# Legacy input remains unversioned; a previous Result must not leak its version.
jq 'del(.observation_definition)' results/source_result.json > results/legacy_result.json
read_values results/legacy_result.json
print_json > results/legacy_estimate.json
jq -e '.estimate_metadata.source_result | has("observation_definition") | not' results/legacy_estimate.json >/dev/null

source scripts/estimation/packages/top_level_package_common.sh
bk_top_level_load_section_package_impls

# Every shipped package declares a version; do not fix their actual versions.
for package_file in scripts/estimation/section_packages/*.sh; do
  package_name=${package_file##*/}
  package_name=${package_name%.sh}
  metadata_fn="bk_section_package_metadata_${package_name}"
  if declare -F "$metadata_fn" >/dev/null; then
    "$metadata_fn" | jq -e '.version | type == "string" and length > 0' >/dev/null
  fi
done

# Distinct versions expose confusion between requested and applied packages.
bk_section_package_metadata_half() {
  printf '%s\n' '{"name":"half","version":"half-2","fallback_target":"identity"}'
}
bk_section_package_metadata_identity() {
  printf '%s\n' '{"name":"identity","version":"identity-3"}'
}
bk_section_package_metadata_trace_mpi_basic() {
  printf '%s\n' '{"name":"trace_mpi_basic","version":"trace-4","fallback_target":"identity"}'
}

input='{"name":"compute","time":8,"estimation_package":"half","estimation_package_version":"old-applied","requested_estimation_package":"old-request","requested_estimation_package_version":"old-request-version"}'
before_input="$input"
direct=$(bk_top_level_dispatch_bound_item "$input" 1 1 1 section "")
test "$input" = "$before_input"
printf '%s\n' "$direct" | jq -e '
  .time == 4 and .estimation_package == "half" and .estimation_package_version == "half-2" and
  .requested_estimation_package == "half" and .requested_estimation_package_version == "half-2"
' >/dev/null

fallback=$(bk_top_level_dispatch_bound_item '{"name":"comm","time":8,"estimation_package":"trace_mpi_basic"}' 1 1 1 section "")
printf '%s\n' "$fallback" | jq -e '
  .time == 8 and .estimation_package == "identity" and .estimation_package_version == "identity-3" and
  .requested_estimation_package == "trace_mpi_basic" and .requested_estimation_package_version == "trace-4"
' >/dev/null

# A successful legacy/custom implementation can lack a version declaration.
bk_section_package_metadata_unversioned() {
  bk_fixed_factor_section_package_metadata unversioned ""
}
bk_section_package_check_applicability_unversioned() {
  printf '%s\n' '{"status":"applicable"}'
}
bk_section_package_transform_unversioned() {
  printf '%s\n' "$1"
}
unknown=$(bk_top_level_dispatch_bound_item '{"name":"legacy","time":8,"estimation_package":"unversioned","estimation_package_version":"stale"}' 1 1 1 section "")
printf '%s\n' "$unknown" | jq -e '
  .time == 8 and .estimation_package_version == null and .requested_estimation_package_version == null
' >/dev/null
unresolved=$(bk_top_level_dispatch_bound_item '{"name":"missing","time":8,"estimation_package":"missing"}' 1 1 1 section "")
printf '%s\n' "$unresolved" | jq -e '
  .time == null and .estimation_package_version == null and .requested_estimation_package_version == null
' >/dev/null
observed='{"name":"observed-only","time":8}'
test "$(bk_top_level_dispatch_bound_item "$observed" 1 1 1 section "")" = "$observed"

# A known requested revision can remain unresolved, without an applied revision.
bk_section_package_metadata_missing() {
  printf '%s\n' '{"name":"missing","version":"missing-5"}'
}
known_unresolved=$(bk_top_level_dispatch_bound_item '{"name":"missing","time":8,"estimation_package":"missing"}' 1 1 1 section "")
printf '%s\n' "$known_unresolved" | jq -e '
  .time == null and .requested_estimation_package_version == "missing-5" and .estimation_package_version == null
' >/dev/null

overlap=$(bk_top_level_dispatch_bound_item '{"sections":["compute","comm"],"time":2,"estimation_package":"identity"}' 1 1 1 overlap "")
printf '%s\n' "$overlap" | jq -e '.time == 2 and .estimation_package_version == "identity-3"' >/dev/null

# Versions survive both Estimate sides through the actual JSON emitter.
est_current_fom_breakdown=$(jq -cn --argjson section "$direct" --argjson overlap "$overlap" '{sections:[$section],overlaps:[$overlap]}')
est_future_fom_breakdown=$(jq -cn --argjson section "$fallback" '{sections:[$section],overlaps:[]}')
print_json > results/package_versions.json
jq -e '
  .current_system.fom_breakdown.sections[0].estimation_package_version == "half-2" and
  .current_system.fom_breakdown.overlaps[0].estimation_package_version == "identity-3" and
  .future_system.fom_breakdown.sections[0].requested_estimation_package_version == "trace-4" and
  .future_system.fom_breakdown.sections[0].estimation_package_version == "identity-3"
' results/package_versions.json >/dev/null

popd >/dev/null

echo "estimation common JSON contract test passed"
