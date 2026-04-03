#!/bin/bash
# estimate.sh — Reference package-based estimation entrypoint for qws

source scripts/estimate_common.sh
source scripts/estimation/packages/lightweight_fom_scaling.sh

BK_ESTIMATION_PACKAGE="lightweight_fom_scaling"
BK_ESTIMATION_BASELINE_SYSTEM="Fugaku"
BK_ESTIMATION_BASELINE_EXP="CASE0"
BK_ESTIMATION_FUTURE_SYSTEM="FugakuNEXT"
BK_ESTIMATION_FUTURE_FOM_FACTOR="${BK_ESTIMATION_FUTURE_FOM_FACTOR:-1}"
BK_ESTIMATION_MODEL_NAME="scale-mock"
BK_ESTIMATION_MODEL_VERSION="0.1"
BK_ESTIMATION_INPUT_JSON="$1"

read_values "$BK_ESTIMATION_INPUT_JSON"

BK_ESTIMATION_CURRENT_TARGET_NODES="${BK_ESTIMATION_CURRENT_TARGET_NODES:-$est_node_count}"
BK_ESTIMATION_FUTURE_TARGET_NODES="${BK_ESTIMATION_FUTURE_TARGET_NODES:-$est_node_count}"

if ! bk_estimation_package_check_applicability; then
  echo "ERROR: estimation package ${BK_ESTIMATION_PACKAGE} is not applicable for input ${BK_ESTIMATION_INPUT_JSON}" >&2
  exit 1
fi

bk_estimation_package_run
bk_estimation_package_apply_metadata

mkdir -p results
output_file="results/estimate_${est_code}_0.json"
print_json > "$output_file"
echo "Estimate written to $output_file"
