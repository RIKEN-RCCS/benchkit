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
resolved_result_timestamp="$(jq -r '.estimate_metadata.source_result_timestamp // .estimate_metadata.source_result.timestamp // empty' results/source_estimate.json)"
resolved_source_estimate_timestamp="$(jq -r '.estimate_metadata.estimation_result_timestamp // empty' results/source_estimate.json)"
resolved_current_source_result="$(jq -c '.estimate_metadata.current_source_result // empty' results/source_estimate.json)"
resolved_future_source_result="$(jq -c '.estimate_metadata.future_source_result // empty' results/source_estimate.json)"
resolved_source_estimate_package="$(jq -r '.estimate_metadata.estimation_package // empty' results/source_estimate.json)"
resolved_source_requested_package="$(jq -r '.estimate_metadata.requested_estimation_package // empty' results/source_estimate.json)"
resolved_source_method_class="$(jq -r '.estimate_metadata.method_class // empty' results/source_estimate.json)"
resolved_source_detail_level="$(jq -r '.estimate_metadata.detail_level // empty' results/source_estimate.json)"
resolved_source_estimate_pipeline_id="$(jq -r '.pipeline_id // empty' results/source_estimate.json)"
resolved_source_estimate_job="$(jq -r '.estimate_job // empty' results/source_estimate.json)"
resolved_source_estimate_trigger="$(jq -r '.ci_trigger // empty' results/source_estimate.json)"
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
  --arg source_result_timestamp "$resolved_result_timestamp" \
  --arg source_estimate_result_uuid "$resolved_source_estimate_uuid" \
  --arg source_estimate_result_timestamp "$resolved_source_estimate_timestamp" \
  --argjson current_source_result "${resolved_current_source_result:-null}" \
  --argjson future_source_result "${resolved_future_source_result:-null}" \
  --arg source_estimation_package "$resolved_source_estimate_package" \
  --arg source_requested_estimation_package "$resolved_source_requested_package" \
  --arg source_method_class "$resolved_source_method_class" \
  --arg source_detail_level "$resolved_source_detail_level" \
  --arg source_estimate_pipeline_id "$resolved_source_estimate_pipeline_id" \
  --arg source_estimate_job "$resolved_source_estimate_job" \
  --arg source_estimate_trigger "$resolved_source_estimate_trigger" \
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
  + (if $source_result_timestamp != "" then {source_result_timestamp: $source_result_timestamp} else {} end)
  + (if $source_estimate_result_uuid != "" then {source_estimate_result_uuid: $source_estimate_result_uuid} else {} end)
  + (if $source_estimate_result_timestamp != "" then {source_estimate_result_timestamp: $source_estimate_result_timestamp} else {} end)
  + (if $source_estimate_result_uuid != "" then {previous_estimation_result_uuid: $source_estimate_result_uuid} else {} end)
  + (if $source_estimate_result_timestamp != "" then {previous_estimation_result_timestamp: $source_estimate_result_timestamp} else {} end)
  + (if $current_source_result != null then {current_source_result: $current_source_result} else {} end)
  + (if $future_source_result != null then {future_source_result: $future_source_result} else {} end)
  + {
      request: {
        reason: $reason,
        trigger: $trigger,
        scope: $scope,
        baseline_policy: $baseline_policy
      }
    }
  + {
      source_result:
        ({uuid: $source_result_uuid}
        + (if $source_result_timestamp != "" then {timestamp: $source_result_timestamp} else {} end))
    }
  + (if $source_estimate_result_uuid != "" or $source_estimate_result_timestamp != "" or $source_estimation_package != "" or $source_requested_estimation_package != "" or $source_method_class != "" or $source_detail_level != "" or $source_estimate_pipeline_id != "" or $source_estimate_job != "" or $source_estimate_trigger != "" then {
      source_estimate:
        ((if $source_estimate_result_uuid != "" then {uuid: $source_estimate_result_uuid} else {} end)
        + (if $source_estimate_result_timestamp != "" then {timestamp: $source_estimate_result_timestamp} else {} end)
        + (if $source_estimation_package != "" then {estimation_package: $source_estimation_package} else {} end)
        + (if $source_requested_estimation_package != "" then {requested_estimation_package: $source_requested_estimation_package} else {} end)
        + (if $source_method_class != "" then {method_class: $source_method_class} else {} end)
        + (if $source_detail_level != "" then {detail_level: $source_detail_level} else {} end)
        + (if $source_estimate_trigger != "" then {ci_trigger: $source_estimate_trigger} else {} end)
        + (if $source_estimate_pipeline_id != "" then {pipeline_id: $source_estimate_pipeline_id} else {} end)
        + (if $source_estimate_job != "" then {estimate_job: $source_estimate_job} else {} end))
    } else {} end)
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
