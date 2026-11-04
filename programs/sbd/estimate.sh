#!/bin/bash
# SBD Davidson Estimate from local inputs; never submits it.
set -euo pipefail
if [[ $# != 1 ]]; then
  echo 'Usage: estimate.sh RESULT' >&2
  exit 2
fi
source scripts/estimation/common.sh
result_file="$1"
# SBD-specific applicability: the ratio projects this one-rank Davidson FOM.
jq -e '(.code | ascii_downcase) == "sbd" and .FOM_unit == "s"
  and .FOM_version == "davidson_internal_s"
  and (.node_count | tostring) == "1" and (.numproc_node | tostring) == "1"
  and (.system | type == "string" and length > 0)
  and (.Exp | type == "string" and length > 0)
  and (.FOM | tonumber | . > 0 and (isinfinite | not))' "$result_file" >/dev/null
# The normal wrapper supplies only Result; acquisition remains a separate stage.
if [[ -z "${BK_SBD_DAVIDSON_PLAN:-}" ]]; then
  shopt -s nullglob
  plans=(results/*/davidson-plan.json)
  [[ ${#plans[@]} = 1 ]] || { echo 'Require exactly one local Davidson plan' >&2; exit 2; }
  BK_SBD_DAVIDSON_PLAN="${plans[0]}"
fi
BK_SBD_DAVIDSON_PROFILES_DIR="${BK_SBD_DAVIDSON_PROFILES_DIR:-results}"
: "${BK_GPU_LIGHTGBM_SOURCE_GPU:?Set the observed source GPU}"
: "${BK_GPU_LIGHTGBM_TARGET_GPU:?Set the model target GPU}"
: "${BK_ESTIMATION_FUTURE_SYSTEM:?Set the target system}"
work=$(bk_estimation_work_directory "$result_file" sbd_davidson)
python_bin="${BK_ESTIMATION_PYTHON:-python3}"
aggregate=programs/sbd/estimation/aggregate_davidson.py
"$python_bin" -B "$aggregate" --prepare-inputs "$BK_SBD_DAVIDSON_PLAN" \
  --profiles-dir "$BK_SBD_DAVIDSON_PROFILES_DIR" --output-dir "$work" \
  --source-gpu "$BK_GPU_LIGHTGBM_SOURCE_GPU" --target-gpu "$BK_GPU_LIGHTGBM_TARGET_GPU"
bk_estimation_run_jobs gpu_kernel_lightgbm_v11 "$work/jobs.json" "$work"
"$python_bin" -B "$aggregate" --combine "$work" > "$work/predictions.json"
output_file="results/estimate_sbd_$(basename "$result_file")"
nsys_sqlite="$(dirname "$BK_SBD_DAVIDSON_PLAN")/discovery.sqlite"
predictions_file="$work/predictions.json"
samples_file="$work/samples.json"
jq -e '(.model | type == "object") and (.model.version | type == "string" and length > 0)
  and (.estimation_package | type == "string" and length > 0)' "$predictions_file" >/dev/null
projection=$("${BK_ESTIMATION_PYTHON:-python3}" -B programs/sbd/estimation/aggregate_davidson.py \
  --nsys-sqlite "$nsys_sqlite" --predictions "$predictions_file" --samples "$samples_file" \
  --nvtx-range "$(jq -er '.scope.nvtx_range' "$samples_file")")
# Scientific assumptions and the measurement's meaning are app-owned.
assumptions=$(jq -c '.assumptions + [
  "NSYS Davidson ratio applies to the corresponding internal Davidson FOM",
  "The caller associates the supplied Result with this profiling bundle"]' <<< "$projection")
measurement=$(jq -c '{nsys_davidson_wall_seconds:(.source_wall_time_ns / 1e9),source_gpu,target_gpu}' <<< "$projection")
bk_estimation_write_projection "$result_file" "$projection" "$measurement" "$output_file" --assumptions "$assumptions" \
  "nsys:$nsys_sqlite" "predictions:$predictions_file" "samples:$samples_file"
