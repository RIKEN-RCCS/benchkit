#!/bin/bash
# gpu_kernel_lightgbm_v10.sh - Section package for PerfTools LightGBM_model/1.0.

# shellcheck source=scripts/estimation/section_packages/perftools_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/perftools_common.sh"

bk_section_package_metadata_gpu_kernel_lightgbm_v10() {
  cat "${BASH_SOURCE[0]%/*}/gpu_kernel_lightgbm_v10.metadata.json"
}

_bk_gpu_lightgbm_section_key() {
  local section_name="$1"
  printf '%s' "$section_name" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Z0-9' '_'
}

_bk_gpu_lightgbm_section_var() {
  local prefix="$1"
  local section_name="$2"
  local key

  key=$(_bk_gpu_lightgbm_section_key "$section_name")
  printf '%s_%s\n' "$prefix" "$key"
}

_bk_gpu_lightgbm_resolve_section_kernel_selector() {
  local item_json="$1"
  local section_name="$2"
  local key
  local value

  key=$(_bk_gpu_lightgbm_section_key "$section_name")
  for var_name in \
    "BK_GPU_LIGHTGBM_KERNEL_REGEX_${key}" \
    "BK_GPU_KERNEL_SECTION_${key}_REGEX" \
    "BK_GPU_LIGHTGBM_KERNEL_NAME_${key}" \
    "BK_GPU_KERNEL_SECTION_${key}_NAME"; do
    value=$(_bk_gpu_lightgbm_env_value "$var_name")
    if [[ -n "$value" ]]; then
      case "$var_name" in
        *REGEX*) printf 'regex\t%s\n' "$value" ;;
        *) printf 'name\t%s\n' "$value" ;;
      esac
      return 0
    fi
  done

  value=$(echo "$item_json" | jq -r '.kernel_regex // .gpu_kernel_regex // empty')
  if [[ -n "$value" ]]; then
    printf 'regex\t%s\n' "$value"
    return 0
  fi

  value=$(echo "$item_json" | jq -r '.kernel_name // .gpu_kernel_name // empty')
  if [[ -n "$value" ]]; then
    printf 'name\t%s\n' "$value"
    return 0
  fi

  printf '\t\n'
}

_bk_gpu_lightgbm_env_value() {
  local var_name="$1"
  eval "printf '%s\n' \"\${${var_name}:-}\""
}

_bk_gpu_lightgbm_perftools_root() {
  printf '%s\n' "${BK_GPU_LIGHTGBM_PERFTOOLS_ROOT:-${BK_GPU_MLP_PERFTOOLS_ROOT:-${BK_PERFTOOLS_ROOT:-}}}"
}

_bk_gpu_lightgbm_bool_enabled() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

_bk_gpu_lightgbm_fetch_enabled() {
  if [[ -n "${BK_GPU_LIGHTGBM_FETCH_PERFTOOLS:-}" ]]; then
    _bk_gpu_lightgbm_bool_enabled "$BK_GPU_LIGHTGBM_FETCH_PERFTOOLS"
    return $?
  fi

  return 0
}

_bk_gpu_lightgbm_ensure_perftools_root() {
  local root repo="${BK_GPU_LIGHTGBM_PERFTOOLS_REPO:-${BK_GPU_MLP_PERFTOOLS_REPO:-${BK_PERFTOOLS_REPO:-https://github.com/masaaki-kondo/PerfTools.git}}}" ref="${BK_GPU_LIGHTGBM_PERFTOOLS_REF:-${BK_GPU_MLP_PERFTOOLS_REF:-${BK_PERFTOOLS_REF:-main}}}" pin="${BK_GPU_LIGHTGBM_PERFTOOLS_COMMIT:-${BK_GPU_MLP_PERFTOOLS_COMMIT:-${BK_PERFTOOLS_COMMIT:-}}}"
  local fetch_enabled=false
  root=$(_bk_gpu_lightgbm_perftools_root)
  if _bk_gpu_lightgbm_fetch_enabled; then fetch_enabled=true; fi
  bk_perftools_ensure_root "$root" "$repo" "$ref" "$pin" "$fetch_enabled"
}

_bk_gpu_lightgbm_model_dir() {
  local root="$1"

  if [[ -z "$root" ]]; then
    printf '%s\n' ""
    return 0
  fi

  printf '%s\n' "${root}/LightGBM_model/1.0"
}

_bk_gpu_lightgbm_predictor() {
  local root="$1"
  local model_dir

  model_dir=$(_bk_gpu_lightgbm_model_dir "$root")
  if [[ -z "$model_dir" ]]; then
    printf '%s\n' ""
    return 0
  fi

  printf '%s\n' "${model_dir}/AI_model/run_inference.py"
}

_bk_gpu_lightgbm_python_exists() {
  local python_bin="$1"

  if [[ "$python_bin" == */* ]]; then
    [[ -x "$python_bin" ]]
    return $?
  fi

  command -v "$python_bin" >/dev/null 2>&1
}

_bk_gpu_lightgbm_default_python() {
  local candidate

  for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf '%s\n' "python3"
}

_bk_gpu_lightgbm_python_compatible() {
  local python_bin="$1"

  _bk_gpu_lightgbm_python_exists "$python_bin" || return 1
  "$python_bin" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

_bk_gpu_lightgbm_abs_path() {
  local path="$1"
  local dir
  local base

  if [[ -z "$path" ]]; then
    printf '%s\n' ""
    return 0
  fi

  if [[ "$path" == /* ]]; then
    printf '%s\n' "$path"
    return 0
  fi

  dir=$(dirname "$path")
  base=$(basename "$path")
  if [[ -d "$dir" ]]; then
    (cd "$dir" && printf '%s/%s\n' "$PWD" "$base")
  else
    printf '%s/%s\n' "$PWD" "$path"
  fi
}

_bk_gpu_lightgbm_first_artifact_path() {
  local item_json="$1"

  echo "$item_json" | jq -r '(.artifacts // [])[0].path // empty'
}

_bk_gpu_lightgbm_artifact_mode() {
  case "${BK_GPU_LIGHTGBM_ARTIFACT_MODE:-input}" in
    ncu|padata|profiler|profile) printf 'ncu\n' ;;
    prediction) printf 'prediction\n' ;;
    *) printf 'input\n' ;;
  esac
}

_bk_gpu_lightgbm_resolve_section_input_csv() {
  local item_json="$1"
  local section_name="$2"
  local scoped_var
  local value
  local artifact_path

  scoped_var=$(_bk_gpu_lightgbm_section_var "BK_GPU_LIGHTGBM_INPUT_CSV" "$section_name")
  value=$(_bk_gpu_lightgbm_env_value "$scoped_var")
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ -n "${BK_GPU_LIGHTGBM_INPUT_CSV:-}" ]]; then
    printf '%s\n' "$BK_GPU_LIGHTGBM_INPUT_CSV"
    return 0
  fi

  artifact_path=$(_bk_gpu_lightgbm_first_artifact_path "$item_json")
  if [[ -n "$artifact_path" && "$(_bk_gpu_lightgbm_artifact_mode)" == "input" ]]; then
    printf '%s\n' "$artifact_path"
    return 0
  fi

  printf '%s\n' ""
}

_bk_gpu_lightgbm_resolve_section_ncu_archive() {
  local item_json="$1"
  local section_name="$2"
  local scoped_var
  local value
  local artifact_path

  scoped_var=$(_bk_gpu_lightgbm_section_var "BK_GPU_LIGHTGBM_NCU_ARCHIVE" "$section_name")
  value=$(_bk_gpu_lightgbm_env_value "$scoped_var")
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ -n "${BK_GPU_LIGHTGBM_NCU_ARCHIVE:-}" ]]; then
    printf '%s\n' "$BK_GPU_LIGHTGBM_NCU_ARCHIVE"
    return 0
  fi

  artifact_path=$(_bk_gpu_lightgbm_first_artifact_path "$item_json")
  if [[ -n "$artifact_path" ]]; then
    case "$(_bk_gpu_lightgbm_artifact_mode):${artifact_path}" in
      ncu:*|*:*.tgz|*:*.tar.gz)
        printf '%s\n' "$artifact_path"
        return 0
        ;;
    esac
  fi

  printf '%s\n' ""
}

_bk_gpu_lightgbm_resolve_section_metadata() {
  local item_json="$1"
  local section_name="$2"
  local ncu_archive="$3"
  local scoped_var
  local value
  local artifact_path
  local metadata_path

  scoped_var=$(_bk_gpu_lightgbm_section_var "BK_GPU_LIGHTGBM_METADATA_JSON" "$section_name")
  value=$(_bk_gpu_lightgbm_env_value "$scoped_var")
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ -n "${BK_GPU_LIGHTGBM_METADATA_JSON:-}" ]]; then
    printf '%s\n' "$BK_GPU_LIGHTGBM_METADATA_JSON"
    return 0
  fi

  artifact_path="${ncu_archive:-$(_bk_gpu_lightgbm_first_artifact_path "$item_json")}"
  if [[ -n "$artifact_path" ]]; then
    case "$artifact_path" in
      *.tar.gz) metadata_path="${artifact_path%.tar.gz}.metadata.json" ;;
      *.tgz) metadata_path="${artifact_path%.tgz}.metadata.json" ;;
      *) metadata_path="${artifact_path}.metadata.json" ;;
    esac
    if [[ -f "$metadata_path" ]]; then
      printf '%s\n' "$metadata_path"
      return 0
    fi
  fi

  printf '%s\n' ""
}

_bk_gpu_lightgbm_resolve_section_prediction_csv() {
  local item_json="$1"
  local section_name="$2"
  local scoped_var
  local value
  local artifact_path

  scoped_var=$(_bk_gpu_lightgbm_section_var "BK_GPU_LIGHTGBM_PREDICTION_CSV" "$section_name")
  value=$(_bk_gpu_lightgbm_env_value "$scoped_var")
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ -n "${BK_GPU_LIGHTGBM_PREDICTION_CSV:-}" ]]; then
    printf '%s\n' "$BK_GPU_LIGHTGBM_PREDICTION_CSV"
    return 0
  fi

  artifact_path=$(_bk_gpu_lightgbm_first_artifact_path "$item_json")
  if [[ -n "$artifact_path" && "$(_bk_gpu_lightgbm_artifact_mode)" == "prediction" ]]; then
    printf '%s\n' "$artifact_path"
    return 0
  fi

  printf '%s\n' ""
}

_bk_gpu_lightgbm_section_slug() {
  local section_name="$1"
  printf '%s_%s_%s' "${est_code:-unknown}" "$section_name" "${est_uuid:-local}" |
    tr -c 'A-Za-z0-9._-' '_'
}

bk_section_package_check_applicability_gpu_kernel_lightgbm_v10() {
  local item_json="$1"
  local item_kind="$2"
  local section_name
  local prediction_csv
  local input_csv
  local ncu_archive
  local root
  local predictor
  local python_bin="${BK_GPU_LIGHTGBM_PYTHON:-${BK_GPU_MLP_PYTHON:-$(_bk_gpu_lightgbm_default_python)}}"
  local missing=()

  if [[ "$item_kind" != "section" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["item_kind:section_required"]}
EOF
    return 1
  fi

  section_name=$(echo "$item_json" | jq -r '.name // "gpu_section"')
  prediction_csv=$(_bk_gpu_lightgbm_resolve_section_prediction_csv "$item_json" "$section_name")
  input_csv=$(_bk_gpu_lightgbm_resolve_section_input_csv "$item_json" "$section_name")
  ncu_archive=$(_bk_gpu_lightgbm_resolve_section_ncu_archive "$item_json" "$section_name")

  if ! _bk_gpu_lightgbm_python_exists "$python_bin"; then
    missing+=("\"python:${python_bin}\"")
  elif ! _bk_gpu_lightgbm_python_compatible "$python_bin"; then
    missing+=("\"python>=3.11:${python_bin}\"")
  fi

  if [[ -n "$prediction_csv" ]]; then
    if [[ ! -f "$prediction_csv" ]]; then
      missing+=("\"prediction_csv:${prediction_csv}\"")
    fi
  else
    root=$(_bk_gpu_lightgbm_ensure_perftools_root) || {
      printf '%s\n' '{"status":"error","missing_inputs":["perftools_checkout_failed"]}'
      return 1
    }
    predictor=$(_bk_gpu_lightgbm_predictor "$root")

    if [[ -z "$input_csv" && -z "$ncu_archive" ]]; then
      missing+=('"gpu_lightgbm_input_csv"')
    fi
    if [[ -n "$input_csv" && ! -f "$input_csv" ]]; then
      missing+=("\"input_csv:${input_csv}\"")
    fi
    if [[ -n "$ncu_archive" && ! -f "$ncu_archive" ]]; then
      missing+=("\"ncu_archive:${ncu_archive}\"")
    fi
    if [[ -z "$root" || ! -d "$root" ]]; then
      missing+=('"BK_GPU_LIGHTGBM_PERFTOOLS_ROOT"')
    fi
    if [[ -z "$predictor" || ! -f "$predictor" ]]; then
      missing+=('"PerfTools LightGBM_model/1.0/AI_model/run_inference.py"')
    fi
  fi

  if (( ${#missing[@]} > 0 )); then
    printf '{"status":"not_applicable","missing_inputs":[%s]}\n' "$(IFS=,; echo "${missing[*]}")"
    return 1
  fi

  cat <<'EOF'
{"status":"applicable","missing_inputs":[]}
EOF
}

_bk_gpu_lightgbm_parse_prediction_csv() {
  local prediction_csv="$1"
  local input_csv="$2"
  local package_name="$3"
  local model_version="$4"
  local python_bin="${BK_GPU_LIGHTGBM_PYTHON:-${BK_GPU_MLP_PYTHON:-$(_bk_gpu_lightgbm_default_python)}}"

  "$python_bin" - "$prediction_csv" "$input_csv" "$package_name" "$model_version" <<'PY'
import csv
import json
import math
from pathlib import Path
import sys

prediction_csv, input_csv, package_name, model_version = sys.argv[1:5]

time_columns = [
    "O-Execution Time",
    "O-Execution Time [ns]",
    "Execution Time [ns]",
    "Predicted Execution Time [ns]",
    "predicted_execution_time_ns",
]
name_columns = ["meta-kernel", "kernel_name", "Kernel Name", "kernel", "Kernel", "name", "Name"]
source_columns = ["meta-src_gpu", "src_gpu", "source_gpu"]
target_columns = ["meta-tgt_gpu", "tgt_gpu", "target_gpu"]
source_time_columns = [
    "Duration [ns]",
    "Execution Time",
    "Execution Time [ns]",
    "gpu__time_duration.sum",
]
metric_columns = [
    "O-Memory Throughput [%]",
    "O-Achieved Occupancy",
    "O-breakdown_memory",
    "O-breakdown_pipeline_contention",
    "O-breakdown_sync",
    "O-breakdown_scheduling_overhead",
]


def cleaned_lines(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            yield line


def as_number(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def read_csv_rows(path):
    reader = csv.DictReader(cleaned_lines(path))
    if not reader.fieldnames:
        return [], []
    return list(reader), reader.fieldnames


def source_time_by_row(path):
    if not path:
        return [], None
    candidate = Path(path)
    if not candidate.is_file():
        return [], None

    rows, fieldnames = read_csv_rows(path)
    if not fieldnames:
        return [], None

    time_column = next((col for col in source_time_columns if col in fieldnames), None)
    if time_column is None:
        return [None] * len(rows), None

    return [as_number(row.get(time_column)) for row in rows], time_column


def source_metric_candidates(metric_name):
    candidates = [metric_name]
    if metric_name.startswith("O-"):
        candidates.append(metric_name[2:])
    if metric_name.startswith("brk_"):
        candidates.append("breakdown_" + metric_name[4:])
    if metric_name.startswith("breakdown_"):
        candidates.append("brk_" + metric_name[len("breakdown_"):])
    return list(dict.fromkeys(candidates))


def source_metrics_by_row(path):
    if not path:
        return []
    candidate = Path(path)
    if not candidate.is_file():
        return []

    rows, fieldnames = read_csv_rows(path)
    if not fieldnames:
        return []

    source_rows = []
    for row in rows:
        source_metrics = {}
        for metric_name in metric_columns:
            for source_name in source_metric_candidates(metric_name):
                if source_name in fieldnames:
                    value = as_number(row.get(source_name))
                    if value is not None:
                        source_metrics[metric_name] = value
                        break
        source_rows.append(source_metrics)
    return source_rows


def metric_comparisons(source_metrics, predicted_metrics):
    comparisons = []
    for metric_name in sorted(set(source_metrics) | set(predicted_metrics)):
        item = {"name": metric_name}
        source_value = source_metrics.get(metric_name)
        predicted_value = predicted_metrics.get(metric_name)
        if source_value is not None:
            item["source_value"] = source_value
        if predicted_value is not None:
            item["predicted_value"] = predicted_value
        if source_value not in (None, 0) and predicted_value is not None:
            item["ratio_predicted_over_source"] = predicted_value / source_value
        comparisons.append(item)
    return comparisons


reader = csv.DictReader(cleaned_lines(prediction_csv))
if not reader.fieldnames:
    raise SystemExit(f"prediction CSV has no header: {prediction_csv}")

time_column = next((col for col in time_columns if col in reader.fieldnames), None)
if time_column is None:
    raise SystemExit(
        "prediction CSV does not contain a supported execution-time column: "
        + ", ".join(time_columns)
    )

kernels = []
source_gpus = []
target_gpus = []
total_seconds = 0.0
source_times_ns, source_time_column = source_time_by_row(input_csv)
source_metrics_rows = source_metrics_by_row(input_csv)
total_source_seconds = 0.0
source_time_count = 0

for idx, row in enumerate(reader, start=1):
    predicted_ns = as_number(row.get(time_column))
    if predicted_ns is None:
        raise SystemExit(f"row {idx} has no numeric predicted execution time in {time_column}")

    raw_name = next((row.get(col, "").strip() for col in name_columns if row.get(col, "").strip()), "")
    source_gpu = next((row.get(col, "").strip() for col in source_columns if row.get(col, "").strip()), "")
    target_gpu = next((row.get(col, "").strip() for col in target_columns if row.get(col, "").strip()), "")
    if source_gpu:
        source_gpus.append(source_gpu)
    if target_gpu:
        target_gpus.append(target_gpu)

    seconds = predicted_ns / 1e9
    total_seconds += seconds
    source_ns = source_times_ns[idx - 1] if idx - 1 < len(source_times_ns) else None
    source_metrics = source_metrics_rows[idx - 1] if idx - 1 < len(source_metrics_rows) else {}
    source_seconds = source_ns / 1e9 if source_ns is not None else None
    if source_seconds is not None:
        total_source_seconds += source_seconds
        source_time_count += 1

    metrics = {
        key: as_number(row.get(key))
        for key in metric_columns
        if key in row and as_number(row.get(key)) is not None
    }
    kernel = {
        "name": raw_name or f"kernel_{idx}",
        "predicted_time_ns": predicted_ns,
        "predicted_time": seconds,
    }
    if source_ns is not None:
        kernel["source_time_ns"] = source_ns
        kernel["source_time"] = source_seconds
        if source_ns != 0:
            kernel["time_ratio_predicted_over_source"] = predicted_ns / source_ns
        if predicted_ns != 0:
            kernel["speedup_factor_source_over_predicted"] = source_ns / predicted_ns
    if source_gpu:
        kernel["source_gpu"] = source_gpu
    if target_gpu:
        kernel["target_gpu"] = target_gpu
    if metrics:
        kernel["metrics"] = metrics
    if source_metrics:
        kernel["source_metrics"] = source_metrics
    comparisons = metric_comparisons(source_metrics, metrics)
    if comparisons:
        kernel["metric_comparisons"] = comparisons
    kernels.append(kernel)

summary_metrics = {
    "kernel_count": len(kernels),
    "time_column": time_column,
    "total_predicted_time_ns": total_seconds * 1e9,
    "source_gpus": sorted(set(source_gpus)),
    "target_gpus": sorted(set(target_gpus)),
    "kernels": kernels,
}
if source_time_column is not None:
    total_source_ns = total_source_seconds * 1e9
    summary_metrics["source_time_column"] = source_time_column
    summary_metrics["source_time_kernel_count"] = source_time_count
    summary_metrics["total_source_time_ns"] = total_source_ns
    summary_metrics["total_source_time"] = total_source_seconds
    if total_source_ns != 0:
        summary_metrics["time_ratio_predicted_over_source"] = (
            summary_metrics["total_predicted_time_ns"] / total_source_ns
        )
    if summary_metrics["total_predicted_time_ns"] != 0:
        summary_metrics["speedup_factor_source_over_predicted"] = (
            total_source_ns / summary_metrics["total_predicted_time_ns"]
        )

print(json.dumps({
    "time": total_seconds,
    "metrics": summary_metrics,
    "package_applicability": {
        "status": "applicable",
        "missing_inputs": [],
    },
    "model": {
        "type": "cross_gpu_kernel_prediction_model",
        "name": "PerfTools LightGBM_model/1.0",
        "version": model_version,
        "repository": "https://github.com/masaaki-kondo/PerfTools",
    },
    "estimation_package": package_name,
}))
PY
}

_bk_gpu_lightgbm_prepare_input_from_ncu() {
  local ncu_archive="$1"
  local _section_name="$2"
  local output_dir="$3"
  local slug="$4"
  local python_bin="${BK_GPU_LIGHTGBM_PYTHON:-${BK_GPU_MLP_PYTHON:-$(_bk_gpu_lightgbm_default_python)}}"
  local source_gpu="${BK_GPU_LIGHTGBM_SOURCE_GPU:-${BK_GPU_MLP_SOURCE_GPU:-H100}}"
  local prepared_csv="${output_dir}/${slug}_lightgbm_input.csv"
  local script_path="scripts/estimation/prepare_gpu_lightgbm_ncu_input.py"
  local archive_abs
  local prepared_abs

  archive_abs=$(_bk_gpu_lightgbm_abs_path "$ncu_archive")
  prepared_abs=$(_bk_gpu_lightgbm_abs_path "$prepared_csv")

  "$python_bin" "$script_path" \
    --padata "$archive_abs" \
    --source-gpu "$source_gpu" \
    --out-csv "$prepared_abs" >&2

  printf '%s\n' "$prepared_csv"
}

_bk_gpu_lightgbm_run_predictor() {
  local item_json="$1"
  local section_name="$2"
  local root
  local model_dir
  local input_csv
  local ncu_archive
  local output_dir="${BK_GPU_LIGHTGBM_OUTPUT_DIR:-results/estimation_artifacts/gpu_kernel_lightgbm_v10}"
  local prediction_csv
  local prediction_log
  local input_csv_abs
  local prediction_csv_abs
  local prediction_log_abs
  local python_bin="${BK_GPU_LIGHTGBM_PYTHON:-${BK_GPU_MLP_PYTHON:-$(_bk_gpu_lightgbm_default_python)}}"
  local source_gpu="${BK_GPU_LIGHTGBM_SOURCE_GPU:-${BK_GPU_MLP_SOURCE_GPU:-H100}}"
  local target_gpu="${BK_GPU_LIGHTGBM_TARGET_GPU:-${BK_GPU_MLP_TARGET_GPU:-A100}}"
  local package_name=gpu_kernel_lightgbm_v10
  local provenance_json mode=prepared_csv
  local slug

  root=$(_bk_gpu_lightgbm_ensure_perftools_root) || return 1
  model_dir=$(_bk_gpu_lightgbm_model_dir "$root")
  input_csv=$(_bk_gpu_lightgbm_resolve_section_input_csv "$item_json" "$section_name")
  ncu_archive=$(_bk_gpu_lightgbm_resolve_section_ncu_archive "$item_json" "$section_name")
  slug=$(_bk_gpu_lightgbm_section_slug "$section_name")

  mkdir -p "$output_dir"
  if [[ -z "$input_csv" && -n "$ncu_archive" ]]; then
    mode=ncu_archive
    input_csv=$(_bk_gpu_lightgbm_prepare_input_from_ncu "$ncu_archive" "$section_name" "$output_dir" "$slug") || return 1
  fi

  prediction_csv="${output_dir}/${slug}_pred.csv"
  prediction_log="${output_dir}/${slug}.log"
  input_csv_abs=$(_bk_gpu_lightgbm_abs_path "$input_csv")
  prediction_csv_abs=$(_bk_gpu_lightgbm_abs_path "$prediction_csv")
  prediction_log_abs=$(_bk_gpu_lightgbm_abs_path "$prediction_log")

  echo "Running PerfTools LightGBM_model/1.0 for ${section_name}: ${source_gpu}->${target_gpu}" >&2
  if ! (
    # Upstream writes extracted_features.csv beside its model; isolate that output.
    scratch_root=$(mktemp -d) || exit 1
    trap 'rm -rf "$scratch_root"' EXIT
    mkdir -p "$scratch_root/LightGBM_model"
    cp -a "$model_dir" "$scratch_root/LightGBM_model/1.0" || exit 1
    cp -a "$root/data" "$scratch_root/data" || exit 1
    cd "$scratch_root/LightGBM_model/1.0" || exit 1
    "$python_bin" AI_model/run_inference.py \
      --src_gpu="$source_gpu" \
      --tgt_gpu="$target_gpu" \
      --ncu_csv="$input_csv_abs" \
      --out="$prediction_csv_abs" \
      --log="$prediction_log_abs"
  ) >/dev/null; then
    echo "ERROR: PerfTools LightGBM_model/1.0 inference failed" >&2
    return 1
  fi

  if [[ ! -s "$prediction_csv_abs" ]]; then
    echo "ERROR: PerfTools LightGBM_model/1.0 did not create prediction CSV: ${prediction_csv_abs}" >&2
    return 1
  fi

  provenance_json=$("$python_bin" scripts/estimation/perftools_provenance.py \
    --root "$root" --version "lightgbm" --predictor "run_inference.py" \
    --source-gpu "${BK_GPU_LIGHTGBM_SOURCE_GPU:-${BK_GPU_MLP_SOURCE_GPU:-H100}}" --target-gpu "${BK_GPU_LIGHTGBM_TARGET_GPU:-${BK_GPU_MLP_TARGET_GPU:-A100}}" \
    --mode "$mode" --input-csv "$input_csv" --prediction-csv "$prediction_csv" \
    --requested-ref "${BK_GPU_LIGHTGBM_PERFTOOLS_REF:-${BK_GPU_MLP_PERFTOOLS_REF:-${BK_PERFTOOLS_REF:-main}}}" --pin "${BK_GPU_LIGHTGBM_PERFTOOLS_COMMIT:-${BK_GPU_MLP_PERFTOOLS_COMMIT:-${BK_PERFTOOLS_COMMIT:-}}}" \
    --output "results/estimation_artifacts/${package_name}/${slug}_provenance.json") || return 1
  printf '%s\t%s\t%s\t%s\n' "$prediction_csv" "$input_csv" "$prediction_log" "$provenance_json"
}

bk_section_package_transform_gpu_kernel_lightgbm_v10() {
  local item_json="$1"
  local _target_nodes="$2"
  local _bench_nodes="$3"
  local _default_factor="$4"
  local _item_kind="$5"
  local section_name
  local prediction_csv
  local input_csv=""
  local prediction_log=""
  local provenance_json="" provenance_path provenance_python
  local run_outputs
  local parsed_json
  local package_name="gpu_kernel_lightgbm_v10"
  local model_version="${BK_GPU_LIGHTGBM_MODEL_VERSION:-1.0}"
  local selector_kind=""
  local selector_value=""
  local selector
  local ncu_archive
  local metadata_json_path=""
  local metadata_json="{}"

  section_name=$(echo "$item_json" | jq -r '.name // "gpu_section"')
  selector=$(_bk_gpu_lightgbm_resolve_section_kernel_selector "$item_json" "$section_name")
  IFS=$'\t' read -r selector_kind selector_value <<< "$selector"
  prediction_csv=$(_bk_gpu_lightgbm_resolve_section_prediction_csv "$item_json" "$section_name")
  input_csv=$(_bk_gpu_lightgbm_resolve_section_input_csv "$item_json" "$section_name")
  ncu_archive=$(_bk_gpu_lightgbm_resolve_section_ncu_archive "$item_json" "$section_name")
  metadata_json_path=$(_bk_gpu_lightgbm_resolve_section_metadata "$item_json" "$section_name" "$ncu_archive")
  if [[ -n "$metadata_json_path" && -f "$metadata_json_path" ]]; then
    metadata_json=$(bk_estimation_read_gpu_profile_metadata "$metadata_json_path")
  fi

  if [[ -z "$prediction_csv" ]]; then
    run_outputs=$(_bk_gpu_lightgbm_run_predictor "$item_json" "$section_name") || return 1
    IFS=$'\t' read -r prediction_csv input_csv prediction_log provenance_json <<< "$run_outputs"
  fi

  if [[ -z "$provenance_json" ]]; then
    provenance_python="${BK_GPU_LIGHTGBM_PYTHON:-${BK_GPU_MLP_PYTHON:-$(_bk_gpu_lightgbm_default_python)}}"
    provenance_path="results/estimation_artifacts/${package_name}/$(_bk_gpu_lightgbm_section_slug "$section_name")_provenance.json"
    provenance_json=$("$provenance_python" scripts/estimation/perftools_provenance.py \
      --mode precomputed_prediction --input-csv "$input_csv" --prediction-csv "$prediction_csv" \
      --output "$provenance_path") || return 1
  fi
  parsed_json=$(_bk_gpu_lightgbm_parse_prediction_csv "$prediction_csv" "$input_csv" "$package_name" "$model_version")

  echo "$item_json" | jq -c \
    --argjson model_provenance "$provenance_json" \
    --arg prediction_csv "$prediction_csv" \
    --arg input_csv "$input_csv" \
    --arg prediction_log "$prediction_log" \
    --arg selector_kind "$selector_kind" \
    --arg selector_value "$selector_value" \
    --arg metadata_json_path "$metadata_json_path" \
    --argjson discovery_metadata "$metadata_json" \
    --argjson parsed "$parsed_json" '
    def selector_matches($kind; $value):
      if $kind == "" or $value == "" then true
      elif $kind == "regex" then ((.name // "") | test($value))
      else ((.name // "") == $value)
      end;
    def ratio_from_kernels($kernels):
      ($kernels | map(.source_time_ns // null) | map(select(. != null)) | add // null) as $source_ns
      | ($kernels | map(.predicted_time_ns // null) | map(select(. != null)) | add // null) as $predicted_ns
      | if ($source_ns != null and $source_ns != 0 and $predicted_ns != null) then ($predicted_ns / $source_ns) else null end;
    .
    | ((.time // .bench_time // null) | if . == null then null else tonumber? end) as $source_section_time
    | (($parsed.metrics.kernels // []) | map(select(selector_matches($selector_kind; $selector_value)))) as $matched_kernels
    | ($matched_kernels | map(.name // "") | unique | sort) as $kernel_names
    | ($kernel_names | length) as $unique_kernel_count
    | ($parsed.metrics.kernels // [] | map(.name // "") | unique | sort) as $available_kernel_names
    | (
        if $unique_kernel_count == 1 then ratio_from_kernels($matched_kernels)
        else null
        end
      ) as $matched_time_ratio
    | ($matched_time_ratio // $parsed.metrics.time_ratio_predicted_over_source // null) as $time_ratio
    | (($parsed.package_applicability.missing_inputs // [])
        + (if $source_section_time == null then ["app_gpu_section_time"] else [] end)
        + (if $time_ratio == null then ["gpu_kernel_time_ratio_predicted_over_source"] else [] end)
        + (if $unique_kernel_count == 0 then ["gpu_kernel_section_kernel_selector_no_match"] else [] end)
        + (if (($selector_kind == "" or $selector_value == "") and (($parsed.metrics.kernels // []) | map(.name // "") | unique | length) > 1) then ["gpu_kernel_section_kernel_selector_required"] else [] end)
        + (if $unique_kernel_count > 1 then ["gpu_kernel_section_kernel_selector_ambiguous"] else [] end)
      ) as $missing_inputs
    | ($source_section_time != null and $time_ratio != null and $unique_kernel_count == 1) as $can_project_section
    | ($source_section_time != null and $time_ratio != null and $unique_kernel_count != 1) as $can_identity_fallback
    | .
    + {
        time: (
          if $can_project_section then ($source_section_time * $time_ratio)
          elif $can_identity_fallback then $source_section_time
          else null
          end
        ),
        bench_time: $source_section_time,
        scaling_method: (if $can_identity_fallback then "identity" else "gpu-kernel-lightgbm-v1.0" end),
        estimation_package: (if $can_identity_fallback then "identity" else $parsed.estimation_package end),
        requested_estimation_package: (if $can_identity_fallback then $parsed.estimation_package else (.requested_estimation_package // $parsed.estimation_package) end),
        fallback_used: (if $can_identity_fallback then "identity" else null end),
        package_applicability: (
          if $can_identity_fallback then
            {status: "fallback", missing_inputs: ($missing_inputs | unique)}
          elif ($missing_inputs | length) == 0 then
            $parsed.package_applicability
          else
            {status: "not_applicable", missing_inputs: ($missing_inputs | unique)}
          end
        ),
        model: ($parsed.model + {provenance: $model_provenance}),
        metrics: (
          $parsed.metrics
          + {
              sample_predicted_time: $parsed.time,
              app_gpu_section_time: $source_section_time,
              unique_kernel_count: $unique_kernel_count,
              kernel_names: $kernel_names,
              available_kernel_names: $available_kernel_names,
              kernel_selector: {
                kind: (if $selector_kind == "" then null else $selector_kind end),
                value: (if $selector_value == "" then null else $selector_value end)
              },
              matched_kernels: $matched_kernels,
              section_time_ratio_predicted_over_source: $time_ratio
            }
          + (if ($discovery_metadata | length) > 0 then {
              nsys_discovery: ($discovery_metadata.nsys_discovery // $discovery_metadata),
              nsys_discovery_metadata_path: $metadata_json_path
            } else {} end)
        )
      }
    | if .fallback_used == null then del(.fallback_used) else . end
    | .artifacts = (
        (.artifacts // [])
        + [{kind: "external_model_provenance", path: $model_provenance.manifest}]
        + [{kind: "gpu_lightgbm_prediction_csv", path: $prediction_csv}]
        + (if $input_csv != "" then [{kind: "gpu_lightgbm_input_csv", path: $input_csv}] else [] end)
        + (if $prediction_log != "" then [{kind: "gpu_lightgbm_log", path: $prediction_log}] else [] end)
        + (if $metadata_json_path != "" then [{kind: "gpu_kernel_profile_metadata", path: $metadata_json_path}] else [] end)
      )
  '
}
