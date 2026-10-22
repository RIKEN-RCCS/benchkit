#!/bin/bash
# Shared current-model adapter; legacy MLP packages remain explicitly selectable.
# shellcheck source=scripts/estimation/section_packages/perftools_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/perftools_common.sh"

_bk_gpu_neural_value() {
  local field="$1" section="$2" key var
  key=$(printf '%s' "$section" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Z0-9' '_')
  for var in "BK_GPU_NEURAL_${field}_${key}" "BK_GPU_NEURAL_${field}" "BK_GPU_MLP_${field}_${key}" "BK_GPU_MLP_${field}"; do
    if [[ -n "${!var:-}" ]]; then printf '%s\n' "${!var}"; return 0; fi
  done
}

_bk_gpu_neural_root() {
  bk_perftools_ensure_root \
    "${BK_GPU_NEURAL_PERFTOOLS_REPO:-${BK_GPU_MLP_PERFTOOLS_REPO:-${BK_PERFTOOLS_REPO:-https://github.com/masaaki-kondo/PerfTools.git}}}" \
    "${BK_GPU_NEURAL_PERFTOOLS_REF:-${BK_GPU_MLP_PERFTOOLS_REF:-${BK_PERFTOOLS_REF:-main}}}" \
    "${BK_GPU_NEURAL_PERFTOOLS_COMMIT:-${BK_GPU_MLP_PERFTOOLS_COMMIT:-${BK_PERFTOOLS_COMMIT:-}}}"
}

_bk_gpu_neural_input() {
  local item="$1" section="$2" input archive
  input=$(_bk_gpu_neural_value INPUT_CSV "$section")
  archive=$(_bk_gpu_neural_value NCU_ARCHIVE "$section")
  if [[ -n "$input" ]]; then
    printf '%s\t%s\n' --wide-csv "$input"
  else
    archive="${archive:-$(jq -r '(.artifacts // [])[0].path // empty' <<< "$item")}"
    printf '%s\t%s\n' --padata "$archive"
  fi
}

_bk_gpu_neural_check() {
  local item="$1" kind="$2" model="$3" root section flag input family release entry
  local python="${BK_GPU_NEURAL_PYTHON:-${BK_GPU_MLP_PYTHON:-python3}}"
  if [[ "$kind" != section ]] || ! "$python" -c 'import sys, numpy, pandas, torch; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    printf '%s\n' '{"status":"not_applicable","missing_inputs":["section_and_python>=3.11_numpy_pandas_torch_required"]}'
    return 1
  fi
  section=$(jq -r '.name // "gpu_section"' <<< "$item")
  IFS=$'\t' read -r flag input < <(_bk_gpu_neural_input "$item" "$section")
  if [[ ! -f "$input" ]] || [[ -z "$(_bk_gpu_neural_value SOURCE_GPU "$section")" || -z "$(_bk_gpu_neural_value TARGET_GPU "$section")" ]]; then
    printf '%s\n' '{"status":"not_applicable","missing_inputs":["wide_ncu_csv_or_archive_and_explicit_source_target_gpu"]}'
    return 1
  fi
  root=$(_bk_gpu_neural_root) || {
    printf '%s\n' '{"status":"error","missing_inputs":["perftools_checkout_failed"]}'
    return 1
  }
  case "$model" in
    mlp455) family=MLP_NN; release=v4.55; entry=mlp-nn.py ;;
    pinn325) family=PINN; release=v3.25; entry=pinn.py ;;
    *) return 1 ;;
  esac
  if [[ ! -f "$root/$family/$entry" || ! -f "$root/$family/$release/meta.pkl" || ! -f "$root/examples/kernel_inputs/prepare_data.py" ]]; then
    printf '%s\n' '{"status":"not_applicable","missing_inputs":["current_perftools_model_release"]}'
    return 1
  fi
  printf '%s\n' '{"status":"applicable","missing_inputs":[]}'
}

_bk_gpu_neural_transform() {
  local item="$1" model="$2" root section flag input key output
  local python="${BK_GPU_NEURAL_PYTHON:-${BK_GPU_MLP_PYTHON:-python3}}"
  root=$(_bk_gpu_neural_root) || return 1
  section=$(jq -r '.name // "gpu_section"' <<< "$item")
  key=$(printf '%s_%s_%s' "${est_code:-section}" "$section" "${est_uuid:-local}" | tr -c 'A-Za-z0-9._-' '_')
  output="${BK_GPU_NEURAL_OUTPUT_DIR:-results/estimation_artifacts}/gpu_kernel_${model}/${key}"
  IFS=$'\t' read -r flag input < <(_bk_gpu_neural_input "$item" "$section")
  printf '%s\n' "$item" | "$python" scripts/estimation/run_gpu_neural.py \
    --model "$model" --root "$root" "$flag" "$input" --output-dir "$output" \
    --source-gpu "$(_bk_gpu_neural_value SOURCE_GPU "$section")" \
    --target-gpu "$(_bk_gpu_neural_value TARGET_GPU "$section")" \
    --profile-process-id "$(_bk_gpu_neural_value PROFILE_PROCESS_ID "$section")" \
    --kernel-name "$(_bk_gpu_neural_value KERNEL_NAME "$section")" \
    --kernel-regex "$(_bk_gpu_neural_value KERNEL_REGEX "$section")" \
    --requested-ref "${BK_GPU_NEURAL_PERFTOOLS_REF:-${BK_GPU_MLP_PERFTOOLS_REF:-${BK_PERFTOOLS_REF:-main}}}" \
    --pin "${BK_GPU_NEURAL_PERFTOOLS_COMMIT:-${BK_GPU_MLP_PERFTOOLS_COMMIT:-${BK_PERFTOOLS_COMMIT:-}}}"
}
