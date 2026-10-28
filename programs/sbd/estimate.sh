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
source scripts/estimation/section_packages/gpu_kernel_lightgbm_v11.sh
work="results/estimation_artifacts/sbd_davidson/$(basename "$result_file" .json)"
python_bin="${BK_ESTIMATION_PYTHON:-python3}"
aggregate=programs/sbd/estimation/aggregate_davidson.py
"$python_bin" -B "$aggregate" --prepare-inputs "$BK_SBD_DAVIDSON_PLAN" \
  --profiles-dir "$BK_SBD_DAVIDSON_PROFILES_DIR" --output-dir "$work" \
  --source-gpu "$BK_GPU_LIGHTGBM_SOURCE_GPU" --target-gpu "$BK_GPU_LIGHTGBM_TARGET_GPU"
# A bundle must not be bypassed by precomputed/scoped per-kernel overrides.
while IFS= read -r variable; do
  case "$variable" in
    BK_GPU_LIGHTGBM_INPUT_CSV*|BK_GPU_LIGHTGBM_PREDICTION_CSV*|BK_GPU_LIGHTGBM_NCU_ARCHIVE*|BK_GPU_LIGHTGBM_METADATA_JSON*)
      [[ -z "${!variable}" ]] || { echo "Conflicting bundle override: $variable" >&2; exit 2; } ;;
  esac
done < <(compgen -A variable BK_GPU_LIGHTGBM_)
for i in 0 1 2 3 4; do
  job=$(jq -c ".[$i]" "$work/jobs.json")
  # Reuse conversion/inference/provenance; each component has its own outputs.
  BK_GPU_LIGHTGBM_NCU_ARCHIVE=$(jq -r .archive <<< "$job") \
  BK_GPU_LIGHTGBM_METADATA_JSON=$(jq -r .metadata <<< "$job") \
  BK_GPU_LIGHTGBM_OUTPUT_DIR="$work/kernel_$i" \
    bk_section_package_transform_gpu_kernel_lightgbm_v11 \
      "$(jq -c .item <<< "$job")" 1 1 1 section > "$work/kernel_$i.json"
done
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
read_values "$result_file"
est_current_system="$est_system"
est_future_system="$BK_ESTIMATION_FUTURE_SYSTEM"
est_current_target_nodes=1
est_future_target_nodes=1
est_current_fom="$est_fom"
est_future_fom=$(jq -er --argjson fom "$est_fom" \
  '$fom * .time_ratio_predicted_over_source | select(. > 0 and (isinfinite | not))' <<< "$projection")
est_current_scaling_method=identity
est_future_scaling_method=$(jq -r .method <<< "$projection")
bk_define_estimation_method_version "$(jq -er .version programs/sbd/estimate.metadata.json)"
bk_estimation_set_package_metadata \
  "$(jq -r .prediction_package <<< "$projection")" \
  "$(jq -r .prediction_model.version <<< "$projection")" cross_system_projection section
bk_estimation_set_current_package_metadata identity \
  "$(jq -r .version scripts/estimation/section_packages/identity.metadata.json)" identity \
  "$(jq -r .version scripts/estimation/section_packages/identity.metadata.json)"
for side in current future; do
  printf -v "est_${side}_bench_system" '%s' "$est_system"
  printf -v "est_${side}_bench_fom" '%s' "$est_fom"
  printf -v "est_${side}_bench_nodes" '%s' "$est_node_count"
  printf -v "est_${side}_bench_numproc_node" '%s' "$est_numproc_node"
  printf -v "est_${side}_bench_uuid" '%s' "$est_uuid"
  printf -v "est_${side}_bench_timestamp" '%s' "$est_timestamp"
done
est_future_model_json=$(jq -c '{type:"cross_system_projection_model",name:.method,
  version:(.schema_version | tostring),projection:.}' <<< "$projection")
est_measurement_json=$(jq -c --argjson fom "$est_fom" '{result_fom_seconds:$fom,
  nsys_davidson_wall_seconds:(.source_wall_time_ns / 1e9),source_gpu,target_gpu}' <<< "$projection")
est_input_artifacts_json=$(jq -cn --arg result "$result_file" --arg nsys "$nsys_sqlite" --arg predictions "$predictions_file" \
  --arg samples "$samples_file" --arg sha "$(sha256sum "$result_file" | cut -d ' ' -f 1)" --argjson p "$projection" \
  '[{kind:"result",path:$result,sha256:$sha},
    {kind:"nsys",path:$nsys,sha256:$p.scope.nsys_sha256},
    {kind:"predictions",path:$predictions,sha256:$p.input_sha256.predictions},
    {kind:"samples",path:$samples,sha256:$p.input_sha256.samples}]')
est_assumptions_json=$(jq -c '.assumptions + [
  "NSYS Davidson ratio applies to the corresponding internal Davidson FOM",
  "The caller associates the supplied Result with this profiling bundle"]' <<< "$projection")
est_notes_json=$(jq -c '{status,limitations,accuracy_verified:false}' <<< "$projection")
bk_estimation_set_applicability applicable
bk_estimation_write_output "$output_file"
