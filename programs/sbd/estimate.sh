#!/bin/bash
# Offline SBD Davidson Estimate; writes JSON to stdout, never submits it.
set -euo pipefail
if [[ $# != 5 ]]; then
  echo 'Usage: bash programs/sbd/estimate.sh RESULT NSYS_SQLITE PREDICTIONS SAMPLES TARGET_SYSTEM' >&2
  exit 2
fi
source scripts/estimation/common.sh
state=$(mktemp)
trap 'rm -f "$state"' EXIT
"${BK_ESTIMATION_PYTHON:-python3}" -B programs/sbd/estimation/prepare_estimate.py "$@" > "$state"
read_values "$1"
while IFS= read -r name; do
  printf -v "$name" '%s' "$(jq -cr --arg name "$name" '.[$name] | if type == "object" or type == "array" then tojson else tostring end' "$state")"
done < <(jq -r 'keys[]' "$state")
est_current_estimation_package_version=$(jq -r .version scripts/estimation/section_packages/identity.metadata.json)
est_requested_current_estimation_package_version="$est_current_estimation_package_version"
est_current_bench_uuid="$est_uuid"
est_current_bench_timestamp="$est_timestamp"
est_future_bench_uuid="$est_uuid"
est_future_bench_timestamp="$est_timestamp"
bk_define_estimation_method_version "$(jq -r .version programs/sbd/estimate.metadata.json)"
print_json | jq -e .
