#!/bin/bash
# Shared current-model adapter; legacy MLP packages remain explicitly selectable.
# shellcheck source=scripts/estimation/section_packages/perftools_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/perftools_common.sh"

_bk_gpu_neural_value() {
  local field="$1" section="$2" key var prefix
  key=$(printf '%s' "$section" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Z0-9' '_')
  for prefix in ${_BK_GPU_NEURAL_PREFIXES:-BK_GPU_NEURAL BK_GPU_MLP}; do
    if [[ -n "$key" ]]; then
      var="${prefix}_${field}_${key}"
      if [[ -n "${!var:-}" ]]; then printf '%s\n' "${!var}"; return 0; fi
    fi
    var="${prefix}_${field}"
    if [[ -n "${!var:-}" ]]; then printf '%s\n' "${!var}"; return 0; fi
  done
}

_bk_gpu_neural_root() {
  local repo ref pin
  repo=$(_bk_gpu_neural_value PERFTOOLS_REPO '')
  ref=$(_bk_gpu_neural_value PERFTOOLS_REF '')
  pin=$(_bk_gpu_neural_value PERFTOOLS_COMMIT '')
  bk_perftools_ensure_root \
    "${repo:-${BK_PERFTOOLS_REPO:-https://github.com/masaaki-kondo/PerfTools.git}}" \
    "${ref:-${BK_PERFTOOLS_REF:-main}}" "${pin:-${BK_PERFTOOLS_COMMIT:-}}"
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
  local item="$1" kind="$2" model="$3" root section flag input declaration
  local _BK_GPU_NEURAL_PREFIXES
  local python="${BK_GPU_NEURAL_PYTHON:-${BK_GPU_MLP_PYTHON:-python3}}"
  if [[ "$kind" != section ]] || ! "$python" -c 'import sys, numpy, pandas, torch; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    printf '%s\n' '{"status":"not_applicable","missing_inputs":["section_and_python>=3.11_numpy_pandas_torch_required"]}'
    return 1
  fi
  declaration=$("$python" scripts/estimation/neural_models.py --model "$model") || return 1
  _BK_GPU_NEURAL_PREFIXES=$(jq -r '.environment_prefixes | join(" ")' <<< "$declaration")
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
  if ! "$python" scripts/estimation/neural_models.py --model "$model" --root "$root" >/dev/null; then
    printf '%s\n' '{"status":"not_applicable","missing_inputs":["declared_perftools_model_dependencies"]}'
    return 1
  fi
  printf '%s\n' '{"status":"applicable","missing_inputs":[]}'
}

_bk_gpu_neural_transform() {
  local item="$1" model="$2" root section flag input key output declaration
  local _BK_GPU_NEURAL_PREFIXES
  local python="${BK_GPU_NEURAL_PYTHON:-${BK_GPU_MLP_PYTHON:-python3}}"
  declaration=$("$python" scripts/estimation/neural_models.py --model "$model") || return 1
  _BK_GPU_NEURAL_PREFIXES=$(jq -r '.environment_prefixes | join(" ")' <<< "$declaration")
  root=$(_bk_gpu_neural_root) || return 1
  section=$(jq -r '.name // "gpu_section"' <<< "$item")
  key=$(printf '%s_%s_%s' "${est_code:-section}" "$section" "${est_uuid:-local}" | tr -c 'A-Za-z0-9._-' '_')
  output="${BK_GPU_NEURAL_OUTPUT_DIR:-results/estimation_artifacts}/gpu_kernel_${model}/${key}"
  IFS=$'\t' read -r flag input < <(_bk_gpu_neural_input "$item" "$section")
  local requested_ref pin
  requested_ref=$(_bk_gpu_neural_value PERFTOOLS_REF '')
  pin=$(_bk_gpu_neural_value PERFTOOLS_COMMIT '')
  printf '%s\n' "$item" | "$python" scripts/estimation/run_gpu_neural.py \
    --model "$model" --root "$root" "$flag" "$input" --output-dir "$output" \
    --source-gpu "$(_bk_gpu_neural_value SOURCE_GPU "$section")" \
    --target-gpu "$(_bk_gpu_neural_value TARGET_GPU "$section")" \
    --profile-process-id "$(_bk_gpu_neural_value PROFILE_PROCESS_ID "$section")" \
    --kernel-name "$(_bk_gpu_neural_value KERNEL_NAME "$section")" \
    --kernel-regex "$(_bk_gpu_neural_value KERNEL_REGEX "$section")" \
    --requested-ref "${requested_ref:-${BK_PERFTOOLS_REF:-main}}" \
    --pin "${pin:-${BK_PERFTOOLS_COMMIT:-}}"
}
