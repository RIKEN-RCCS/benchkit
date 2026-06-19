#!/bin/bash
# gpu_kernel_mlp_v15.sh - Section package and shared implementation for
# PerfTools MLP_NN GPU estimators.

bk_section_package_metadata_gpu_kernel_mlp_v15() {
  cat <<'EOF'
{
  "name": "gpu_kernel_mlp_v15",
  "fallback_target": "identity",
  "source_system_scope": {
    "kind": "benchmark_system",
    "accepted_values": ["any"]
  },
  "target_system_scope": {
    "accepted_values": ["any"]
  },
  "item_kind_scope": ["section"],
  "required_result_fields": ["name", "app-side GPU section time as time or bench_time"],
  "required_artifact_kinds": [
    "PerfTools MLP_NN/v1.5 prepared input CSV",
    "precomputed prediction CSV",
    "or BenchKit padata archive with Nsight Compute raw CSV"
  ],
  "acquisition_mode": "external",
  "output_fields": [
    "time",
    "bench_time",
    "scaling_method",
    "metrics",
    "package_applicability"
  ],
  "not_applicable_when": [
    "item kind is not section",
    "neither section artifact nor BK_GPU_MLP_INPUT_CSV/BK_GPU_MLP_PREDICTION_CSV is available",
    "padata artifact mode is requested but the archive has no Nsight Compute raw CSV",
    "PerfTools checkout is not available when running the external predictor",
    "Python 3.11+ runtime for CSV parsing or external inference is not available",
    "prediction CSV does not contain a recognized execution-time column",
    "prediction/input pair does not provide a source-kernel time ratio",
    "app-side GPU section time is not available"
  ]
}
EOF
}

_bk_gpu_mlp_section_key() {
  local section_name="$1"
  printf '%s' "$section_name" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Z0-9' '_'
}

_bk_gpu_mlp_section_var() {
  local prefix="$1"
  local section_name="$2"
  local key

  key=$(_bk_gpu_mlp_section_key "$section_name")
  printf '%s_%s\n' "$prefix" "$key"
}

_bk_gpu_mlp_resolve_section_kernel_selector() {
  local item_json="$1"
  local section_name="$2"
  local key
  local value

  key=$(_bk_gpu_mlp_section_key "$section_name")
  for var_name in \
    "BK_GPU_MLP_KERNEL_REGEX_${key}" \
    "BK_GPU_KERNEL_SECTION_${key}_REGEX" \
    "BK_GPU_MLP_KERNEL_NAME_${key}" \
    "BK_GPU_KERNEL_SECTION_${key}_NAME"; do
    value=$(_bk_gpu_mlp_env_value "$var_name")
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

_bk_gpu_mlp_env_value() {
  local var_name="$1"
  eval "printf '%s\n' \"\${${var_name}:-}\""
}

_bk_gpu_mlp_perftools_root() {
  printf '%s\n' "${BK_GPU_MLP_PERFTOOLS_ROOT:-${BK_PERFTOOLS_ROOT:-}}"
}

_bk_gpu_mlp_bool_enabled() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

_bk_gpu_mlp_fetch_enabled() {
  if [[ -n "${BK_GPU_MLP_FETCH_PERFTOOLS:-}" ]]; then
    _bk_gpu_mlp_bool_enabled "$BK_GPU_MLP_FETCH_PERFTOOLS"
    return $?
  fi

  return 0
}

_bk_gpu_mlp_ensure_perftools_root() {
  local root
  local repo="${BK_GPU_MLP_PERFTOOLS_REPO:-${BK_PERFTOOLS_REPO:-https://github.com/masaaki-kondo/PerfTools.git}}"
  local ref="${BK_GPU_MLP_PERFTOOLS_REF:-${BK_PERFTOOLS_REF:-main}}"

  root=$(_bk_gpu_mlp_perftools_root)
  if [[ -n "$root" && -f "$(_bk_gpu_mlp_predictor "$root")" ]]; then
    printf '%s\n' "$root"
    return 0
  fi

  if ! _bk_gpu_mlp_fetch_enabled; then
    printf '%s\n' "$root"
    return 0
  fi

  root="${root:-${BK_GPU_MLP_PERFTOOLS_ROOT:-${BK_PERFTOOLS_ROOT:-.benchkit_estimation_tools/PerfTools}}}"
  if [[ ! -f "$(_bk_gpu_mlp_predictor "$root")" ]]; then
    if ! command -v git >/dev/null 2>&1; then
      printf '%s\n' "$root"
      return 0
    fi

    mkdir -p "$(dirname "$root")"
    if [[ ! -d "$root/.git" ]]; then
      echo "Fetching PerfTools for ${BK_GPU_MLP_PACKAGE_NAME:-gpu_kernel_mlp_v15}: ${repo} (${ref})" >&2
      git clone --depth 1 "$repo" "$root" >&2 || {
        printf '%s\n' "$root"
        return 0
      }
    fi
    if [[ "$ref" != "main" && "$ref" != "master" ]]; then
      git -C "$root" fetch --depth 1 origin "$ref" >&2 || true
      git -C "$root" checkout "$ref" >&2 || true
    fi
  fi

  export BK_GPU_MLP_PERFTOOLS_ROOT="$root"
  printf '%s\n' "$root"
}

_bk_gpu_mlp_predictor() {
  local root="$1"
  local version_dir="${BK_GPU_MLP_VERSION_DIR:-v1.5}"
  local predictor_script="${BK_GPU_MLP_PREDICT_SCRIPT:-predict_v15.py}"

  if [[ -z "$root" ]]; then
    printf '%s\n' ""
    return 0
  fi

  printf '%s\n' "${root}/MLP_NN/${version_dir}/${predictor_script}"
}

_bk_gpu_mlp_python_exists() {
  local python_bin="$1"

  if [[ "$python_bin" == */* ]]; then
    [[ -x "$python_bin" ]]
    return $?
  fi

  command -v "$python_bin" >/dev/null 2>&1
}

_bk_gpu_mlp_default_python() {
  local candidate

  for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf '%s\n' "python3"
}

_bk_gpu_mlp_python_compatible() {
  local python_bin="$1"

  _bk_gpu_mlp_python_exists "$python_bin" || return 1
  "$python_bin" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

_bk_gpu_mlp_abs_existing_path() {
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

_bk_gpu_mlp_first_artifact_path() {
  local item_json="$1"

  echo "$item_json" | jq -r '(.artifacts // [])[0].path // empty'
}

_bk_gpu_mlp_resolve_section_input_csv() {
  local item_json="$1"
  local section_name="$2"
  local scoped_var
  local value
  local artifact_path

  scoped_var=$(_bk_gpu_mlp_section_var "BK_GPU_MLP_INPUT_CSV" "$section_name")
  value=$(_bk_gpu_mlp_env_value "$scoped_var")
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ -n "${BK_GPU_MLP_INPUT_CSV:-}" ]]; then
    printf '%s\n' "$BK_GPU_MLP_INPUT_CSV"
    return 0
  fi

  artifact_path=$(_bk_gpu_mlp_first_artifact_path "$item_json")
  if [[ -n "$artifact_path" && "${BK_GPU_MLP_ARTIFACT_MODE:-input}" == "input" ]]; then
    printf '%s\n' "$artifact_path"
    return 0
  fi

  printf '%s\n' ""
}

_bk_gpu_mlp_artifact_mode() {
  case "${BK_GPU_MLP_ARTIFACT_MODE:-input}" in
    ncu|padata|profiler|profile) printf 'ncu\n' ;;
    prediction) printf 'prediction\n' ;;
    *) printf 'input\n' ;;
  esac
}

_bk_gpu_mlp_resolve_section_ncu_archive() {
  local item_json="$1"
  local section_name="$2"
  local scoped_var
  local value
  local artifact_path

  scoped_var=$(_bk_gpu_mlp_section_var "BK_GPU_MLP_NCU_ARCHIVE" "$section_name")
  value=$(_bk_gpu_mlp_env_value "$scoped_var")
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ -n "${BK_GPU_MLP_NCU_ARCHIVE:-}" ]]; then
    printf '%s\n' "$BK_GPU_MLP_NCU_ARCHIVE"
    return 0
  fi

  artifact_path=$(_bk_gpu_mlp_first_artifact_path "$item_json")
  if [[ -n "$artifact_path" ]]; then
    case "$(_bk_gpu_mlp_artifact_mode):${artifact_path}" in
      ncu:*|*:*.tgz|*:*.tar.gz)
        printf '%s\n' "$artifact_path"
        return 0
        ;;
    esac
  fi

  printf '%s\n' ""
}

_bk_gpu_mlp_resolve_section_prediction_csv() {
  local item_json="$1"
  local section_name="$2"
  local scoped_var
  local value
  local artifact_path

  scoped_var=$(_bk_gpu_mlp_section_var "BK_GPU_MLP_PREDICTION_CSV" "$section_name")
  value=$(_bk_gpu_mlp_env_value "$scoped_var")
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ -n "${BK_GPU_MLP_PREDICTION_CSV:-}" ]]; then
    printf '%s\n' "$BK_GPU_MLP_PREDICTION_CSV"
    return 0
  fi

  artifact_path=$(_bk_gpu_mlp_first_artifact_path "$item_json")
  if [[ -n "$artifact_path" && "${BK_GPU_MLP_ARTIFACT_MODE:-input}" == "prediction" ]]; then
    printf '%s\n' "$artifact_path"
    return 0
  fi

  printf '%s\n' ""
}

_bk_gpu_mlp_section_slug() {
  local section_name="$1"
  printf '%s_%s_%s' "${est_code:-unknown}" "$section_name" "${est_uuid:-local}" |
    tr -c 'A-Za-z0-9._-' '_'
}

bk_section_package_check_applicability_gpu_kernel_mlp_v15() {
  local item_json="$1"
  local item_kind="$2"
  local section_name
  local prediction_csv
  local input_csv
  local ncu_archive
  local root
  local predictor
  local python_bin="${BK_GPU_MLP_PYTHON:-$(_bk_gpu_mlp_default_python)}"
  local predictor_rel="MLP_NN/${BK_GPU_MLP_VERSION_DIR:-v1.5}/${BK_GPU_MLP_PREDICT_SCRIPT:-predict_v15.py}"
  local missing=()

  if [[ "$item_kind" != "section" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["item_kind:section_required"]}
EOF
    return 1
  fi

  section_name=$(echo "$item_json" | jq -r '.name // "gpu_section"')
  prediction_csv=$(_bk_gpu_mlp_resolve_section_prediction_csv "$item_json" "$section_name")
  input_csv=$(_bk_gpu_mlp_resolve_section_input_csv "$item_json" "$section_name")
  ncu_archive=$(_bk_gpu_mlp_resolve_section_ncu_archive "$item_json" "$section_name")

  if ! _bk_gpu_mlp_python_exists "$python_bin"; then
    missing+=("\"python:${python_bin}\"")
  elif ! _bk_gpu_mlp_python_compatible "$python_bin"; then
    missing+=("\"python>=3.11:${python_bin}\"")
  fi

  if [[ -n "$prediction_csv" ]]; then
    if [[ ! -f "$prediction_csv" ]]; then
      missing+=("\"prediction_csv:${prediction_csv}\"")
    fi
  else
    root=$(_bk_gpu_mlp_ensure_perftools_root)
    predictor=$(_bk_gpu_mlp_predictor "$root")

    if [[ -z "$input_csv" && -z "$ncu_archive" ]]; then
      missing+=('"gpu_mlp_input_csv"')
    fi
    if [[ -n "$input_csv" && ! -f "$input_csv" ]]; then
      missing+=("\"input_csv:${input_csv}\"")
    fi
    if [[ -n "$ncu_archive" && ! -f "$ncu_archive" ]]; then
      missing+=("\"ncu_archive:${ncu_archive}\"")
    fi
    if [[ -z "$root" || ! -d "$root" ]]; then
      missing+=('"BK_GPU_MLP_PERFTOOLS_ROOT"')
    fi
    if [[ -z "$predictor" || ! -f "$predictor" ]]; then
      missing+=("\"PerfTools predictor:${predictor_rel}\"")
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

_bk_gpu_mlp_parse_prediction_csv() {
  local prediction_csv="$1"
  local input_csv="$2"
  local package_name="$3"
  local model_version="$4"
  local python_bin="${BK_GPU_MLP_PYTHON:-$(_bk_gpu_mlp_default_python)}"

  "$python_bin" - "$prediction_csv" "$input_csv" "$package_name" "$model_version" <<'PY'
import csv
import json
import math
from pathlib import Path
import sys

prediction_csv, input_csv, package_name, model_version = sys.argv[1:5]

time_columns = [
    "Execution Time [ns]",
    "O-Execution Time [ns]",
    "O-Execution Time",
    "Predicted Execution Time [ns]",
    "predicted_execution_time_ns",
]
name_columns = ["kernel_name", "Kernel Name", "kernel", "Kernel", "name", "Name"]
source_time_columns = [
    "Duration [ns]",
    "Execution Time",
    "Execution Time [ns]",
    "gpu__time_duration.sum",
]
metric_columns = [
    "Memory Throughput [%]",
    "Achieved Occupancy",
    "brk_memory",
    "brk_pipeline_contention",
    "brk_sync",
    "brk_scheduling_overhead",
    "t_mem_ns",
    "t_comp_ns",
    "t_roof_ns",
    "efficiency_eta",
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
nonpositive_prediction_count = 0

for idx, row in enumerate(reader, start=1):
    predicted_ns = as_number(row.get(time_column))
    if predicted_ns is None:
        raise SystemExit(f"row {idx} has no numeric predicted execution time in {time_column}")
    if predicted_ns <= 0:
        nonpositive_prediction_count += 1

    raw_name = next((row.get(col, "").strip() for col in name_columns if row.get(col, "").strip()), "")
    source_gpu = (row.get("src_gpu") or row.get("source_gpu") or "").strip()
    target_gpu = (row.get("tgt_gpu") or row.get("target_gpu") or "").strip()
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
if nonpositive_prediction_count:
    summary_metrics["nonpositive_prediction_count"] = nonpositive_prediction_count
    summary_metrics["diagnostics"] = {
        "severity": "warning",
        "reason": "nonpositive_predicted_execution_time",
        "message": (
            f"PerfTools MLP_NN/{model_version} returned non-positive predicted execution "
            "time for one or more kernel rows. Check target GPU selection and "
            "required NCU feature coverage."
        ),
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
        "name": "PerfTools MLP_NN/" + model_version,
        "version": model_version,
        "repository": "https://github.com/masaaki-kondo/PerfTools",
    },
    "estimation_package": package_name,
}))
PY
}

_bk_gpu_mlp_prepare_input_from_ncu() {
  local ncu_archive="$1"
  local section_name="$2"
  local root="$3"
  local output_dir="$4"
  local slug="$5"
  local python_bin="${BK_GPU_MLP_PYTHON:-$(_bk_gpu_mlp_default_python)}"
  local source_gpu="${BK_GPU_MLP_SOURCE_GPU:-${BK_GPU_MLP_SRC_GPU:-H100}}"
  local target_gpu="${BK_GPU_MLP_TARGET_GPU:-${BK_GPU_MLP_TGT_GPU:-A100}}"
  local kernel_count="${BK_GPU_MLP_KERNEL_COUNT:-20}"
  local prepared_csv="${output_dir}/${slug}_input.csv"
  local script_path="scripts/estimation/prepare_gpu_mlp_ncu_input.py"
  local archive_abs
  local prepared_abs

  archive_abs=$(_bk_gpu_mlp_abs_existing_path "$ncu_archive")
  prepared_abs=$(_bk_gpu_mlp_abs_existing_path "$prepared_csv")

  "$python_bin" "$script_path" \
    --padata "$archive_abs" \
    --perftools-root "$root" \
    --source-gpu "$source_gpu" \
    --target-gpu "$target_gpu" \
    --kernel-count "$kernel_count" \
    --out-csv "$prepared_abs" >&2

  printf '%s\n' "$prepared_csv"
}

_bk_gpu_mlp_run_predictor() {
  local item_json="$1"
  local section_name="$2"
  local root
  local input_csv
  local ncu_archive
  local package_name="${BK_GPU_MLP_PACKAGE_NAME:-gpu_kernel_mlp_v15}"
  local version_dir="${BK_GPU_MLP_VERSION_DIR:-v1.5}"
  local predictor_script="${BK_GPU_MLP_PREDICT_SCRIPT:-predict_v15.py}"
  local output_dir="${BK_GPU_MLP_OUTPUT_DIR:-results/estimation_artifacts/${package_name}}"
  local prediction_csv
  local prediction_log
  local input_csv_abs
  local prediction_csv_abs
  local prediction_log_abs
  local python_bin="${BK_GPU_MLP_PYTHON:-$(_bk_gpu_mlp_default_python)}"
  local slug

  root=$(_bk_gpu_mlp_ensure_perftools_root)
  input_csv=$(_bk_gpu_mlp_resolve_section_input_csv "$item_json" "$section_name")
  ncu_archive=$(_bk_gpu_mlp_resolve_section_ncu_archive "$item_json" "$section_name")
  slug=$(_bk_gpu_mlp_section_slug "$section_name")

  mkdir -p "$output_dir"
  if [[ -z "$input_csv" && -n "$ncu_archive" ]]; then
    input_csv=$(_bk_gpu_mlp_prepare_input_from_ncu "$ncu_archive" "$section_name" "$root" "$output_dir" "$slug")
  fi

  prediction_csv="${output_dir}/${slug}_pred.csv"
  prediction_log="${output_dir}/${slug}.log"
  input_csv_abs=$(_bk_gpu_mlp_abs_existing_path "$input_csv")
  prediction_csv_abs=$(_bk_gpu_mlp_abs_existing_path "$prediction_csv")
  prediction_log_abs=$(_bk_gpu_mlp_abs_existing_path "$prediction_log")

  if ! (
    cd "$root"
    "$python_bin" "MLP_NN/${version_dir}/${predictor_script}" \
      --csv "$input_csv_abs" \
      --row "${BK_GPU_MLP_ROW:-all}" \
      --out "$prediction_csv_abs" \
      --log "$prediction_log_abs"
  ) >/dev/null; then
    echo "ERROR: PerfTools MLP_NN/${version_dir} inference failed" >&2
    return 1
  fi

  if [[ ! -s "$prediction_csv_abs" ]]; then
    echo "ERROR: PerfTools MLP_NN/${version_dir} did not create prediction CSV: ${prediction_csv_abs}" >&2
    return 1
  fi

  printf '%s\t%s\t%s\n' "$prediction_csv" "$input_csv" "$prediction_log"
}

bk_section_package_transform_gpu_kernel_mlp_v15() {
  local item_json="$1"
  local _target_nodes="$2"
  local _bench_nodes="$3"
  local _default_factor="$4"
  local _item_kind="$5"
  local section_name
  local prediction_csv
  local input_csv=""
  local prediction_log=""
  local run_outputs
  local parsed_json
  local package_name="${BK_GPU_MLP_PACKAGE_NAME:-gpu_kernel_mlp_v15}"
  local model_version="${BK_GPU_MLP_MODEL_VERSION:-v1.5}"
  local scaling_method="${BK_GPU_MLP_SCALING_METHOD:-gpu-kernel-mlp-${model_version}}"
  local selector_kind=""
  local selector_value=""
  local selector

  section_name=$(echo "$item_json" | jq -r '.name // "gpu_section"')
  selector=$(_bk_gpu_mlp_resolve_section_kernel_selector "$item_json" "$section_name")
  IFS=$'\t' read -r selector_kind selector_value <<< "$selector"
  prediction_csv=$(_bk_gpu_mlp_resolve_section_prediction_csv "$item_json" "$section_name")
  input_csv=$(_bk_gpu_mlp_resolve_section_input_csv "$item_json" "$section_name")

  if [[ -z "$prediction_csv" ]]; then
    run_outputs=$(_bk_gpu_mlp_run_predictor "$item_json" "$section_name")
    IFS=$'\t' read -r prediction_csv input_csv prediction_log <<< "$run_outputs"
  fi

  parsed_json=$(_bk_gpu_mlp_parse_prediction_csv "$prediction_csv" "$input_csv" "$package_name" "$model_version")

  echo "$item_json" | jq -c \
    --arg prediction_csv "$prediction_csv" \
    --arg input_csv "$input_csv" \
    --arg prediction_log "$prediction_log" \
    --arg selector_kind "$selector_kind" \
    --arg selector_value "$selector_value" \
    --arg scaling_method "$scaling_method" \
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
        scaling_method: (if $can_identity_fallback then "identity" else $scaling_method end),
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
        model: $parsed.model,
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
        )
      }
    | if .fallback_used == null then del(.fallback_used) else . end
    | .artifacts = (
        (.artifacts // [])
        + [{kind: "gpu_mlp_prediction_csv", path: $prediction_csv}]
        + (if $input_csv != "" then [{kind: "gpu_mlp_input_csv", path: $input_csv}] else [] end)
        + (if $prediction_log != "" then [{kind: "gpu_mlp_log", path: $prediction_log}] else [] end)
      )
  '
}
