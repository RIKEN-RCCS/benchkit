#!/bin/bash
# Fetch a benchmark result JSON from the result server by UUID.
# Saves the result to results/result0.json for subsequent estimation.
#
# Required CI variables:
#   estimate_result_uuid - UUID of the estimate result to re-estimate from
#   code                 - Program code name (e.g., "qws")
#   RESULT_SERVER        - Base URL of the result server
set -euo pipefail

source "$(dirname "$0")/api.sh"

if [[ -z "${code:-}" ]]; then
  echo "ERROR: code must be specified" >&2
  exit 1
fi

mkdir -p results
rm -f results/reestimation_context.json

if [[ -z "${estimate_result_uuid:-}" ]]; then
  echo "ERROR: estimate_result_uuid must be specified" >&2
  exit 1
fi

resolved_source_estimate_uuid="$estimate_result_uuid"
echo "Fetching estimate for UUID: $estimate_result_uuid"
bk_result_server_get_json_to_file \
  "/api/query/estimate?uuid=${estimate_result_uuid}" \
  "results/source_estimate.json"

resolved_result_uuid="$(jq -r '.estimate_metadata.source_result_uuid // empty' results/source_estimate.json)"
if [[ -z "$resolved_result_uuid" ]]; then
  echo "ERROR: source_result_uuid not found in estimate ${estimate_result_uuid}" >&2
  exit 1
fi
echo "Resolved source result UUID: $resolved_result_uuid"

echo "Fetching result for UUID: $resolved_result_uuid"
bk_result_server_get_json_to_file \
  "/api/query/result?uuid=${resolved_result_uuid}" \
  "results/result0.json"
echo "Fetched result to results/result0.json"

reestimation_reason="${reestimation_reason:-manual-rerun}"
reestimation_trigger="${reestimation_trigger:-ci-reestimation}"
reestimation_scope="${reestimation_scope:-both}"
reestimation_baseline_policy="${reestimation_baseline_policy:-reuse-recorded-baseline}"
jq -cn \
  --arg source_result_uuid "$resolved_result_uuid" \
  --arg source_estimate_result_uuid "$resolved_source_estimate_uuid" \
  --arg reason "$reestimation_reason" \
  --arg trigger "$reestimation_trigger" \
  --arg scope "$reestimation_scope" \
  --arg baseline_policy "$reestimation_baseline_policy" \
  '{
    source_result_uuid: $source_result_uuid,
    reason: $reason,
    trigger: $trigger,
    scope: $scope,
    baseline_policy: $baseline_policy
  }
  + (if $source_estimate_result_uuid != "" then {source_estimate_result_uuid: $source_estimate_result_uuid} else {} end)
  + (if $source_estimate_result_uuid != "" then {previous_estimation_result_uuid: $source_estimate_result_uuid} else {} end)
  ' > results/reestimation_context.json
echo "Wrote re-estimation context to results/reestimation_context.json"

set +e
bk_result_server_download_to_file \
  "/api/query/estimation-inputs?uuid=${resolved_result_uuid}" \
  "results/estimation_inputs.tgz"
download_exit=$?
set -e

if [[ $download_exit -eq 0 && -f "results/estimation_inputs.tgz" ]]; then
  mkdir -p "results/estimation_inputs"
  tar -xzf "results/estimation_inputs.tgz" -C "results/estimation_inputs"
  rm -f "results/estimation_inputs.tgz"
  echo "Restored estimation inputs to results/estimation_inputs/"
else
  rm -f "results/estimation_inputs.tgz"
  echo "No stored estimation inputs found for UUID: $resolved_result_uuid"
fi
