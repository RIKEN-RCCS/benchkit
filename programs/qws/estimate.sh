#!/bin/bash
# estimate.sh — Reference package-based estimation entrypoint for qws

source scripts/estimation/common.sh

BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-instrumented_app_sections_dummy}"
BK_ESTIMATION_BASELINE_SYSTEM="Fugaku"
BK_ESTIMATION_BASELINE_EXP="CASE0"
BK_ESTIMATION_FUTURE_SYSTEM="FugakuNEXT"
BK_ESTIMATION_CURRENT_TARGET_NODES="${BK_ESTIMATION_CURRENT_TARGET_NODES:-1024}"
BK_ESTIMATION_FUTURE_TARGET_NODES="${BK_ESTIMATION_FUTURE_TARGET_NODES:-256}"
BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-0.5}"
BK_ESTIMATION_LOGP_SECTION_NAME="${BK_ESTIMATION_LOGP_SECTION_NAME:-allreduce}"
BK_ESTIMATION_INPUT_JSON="$1"

load_estimation_package() {
  local package_name="$1"

  source "scripts/estimation/packages/${package_name}.sh"
  BK_ESTIMATION_PACKAGE_VERSION=$(bk_estimation_package_metadata | jq -r '.version // empty')
  case "$package_name" in
    weakscaling)
      BK_ESTIMATION_MODEL_NAME="weakscaling"
      BK_ESTIMATION_MODEL_VERSION="0.1"
      ;;
    instrumented_app_sections_dummy)
      BK_ESTIMATION_MODEL_NAME="instrumented-app-sections-dummy"
      BK_ESTIMATION_MODEL_VERSION="0.1"
      ;;
    *)
      echo "ERROR: Unsupported estimation package for qws: ${package_name}" >&2
      exit 1
      ;;
  esac
}

load_estimation_package "$BK_ESTIMATION_PACKAGE"

read_values "$BK_ESTIMATION_INPUT_JSON"

if ! bk_estimation_execute_with_fallback load_estimation_package; then
  echo "ERROR: estimation package ${BK_ESTIMATION_PACKAGE} is not applicable for input ${BK_ESTIMATION_INPUT_JSON}" >&2
  exit 1
fi

mkdir -p results
output_file="results/estimate_${est_code}_0.json"
print_json > "$output_file"
echo "Estimate written to $output_file"
