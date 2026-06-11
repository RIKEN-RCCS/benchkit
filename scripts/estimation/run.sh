#!/bin/bash
# run.sh — Estimation execution wrapper
#
# Called from CI job script section:
#   bash scripts/estimation/run.sh <code>
#
# Discovers result*.json files in results/ and runs the corresponding
# application-specific estimate script for each one.

set -euo pipefail

code="$1"
estimate_script="programs/${code}/estimate.sh"

bk_estimation_bool_enabled() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

bk_estimation_gpu_mlp_perftools_needed() {
  if bk_estimation_bool_enabled "${BK_GPU_MLP_FETCH_PERFTOOLS:-false}"; then
    return 0
  fi

  if [[ "${code:-}" == "genesis" ]] && bk_estimation_bool_enabled "${BK_GENESIS_GPU_MLP_PROFILE:-false}"; then
    return 0
  fi

  if bk_estimation_bool_enabled "${BK_QWS_GPU_MLP_SMOKE:-false}"; then
    case "${BK_QWS_GPU_MLP_SMOKE_MODE:-prediction}" in
      perftools|input|predictor) return 0 ;;
    esac
  fi

  return 1
}

bk_estimation_prepare_gpu_mlp_perftools() {
  local repo="${BK_GPU_MLP_PERFTOOLS_REPO:-https://github.com/masaaki-kondo/PerfTools.git}"
  local ref="${BK_GPU_MLP_PERFTOOLS_REF:-main}"
  local root="${BK_GPU_MLP_PERFTOOLS_ROOT:-.benchkit_estimation_tools/PerfTools}"
  local input_csv
  local use_qws_example=0
  local use_genesis_ncu=0

  if ! bk_estimation_gpu_mlp_perftools_needed; then
    return 0
  fi

  if bk_estimation_bool_enabled "${BK_QWS_GPU_MLP_SMOKE:-false}"; then
    case "${BK_QWS_GPU_MLP_SMOKE_MODE:-prediction}" in
      perftools|input|predictor) use_qws_example=1 ;;
    esac
  fi
  if [[ "${code:-}" == "genesis" ]] && bk_estimation_bool_enabled "${BK_GENESIS_GPU_MLP_PROFILE:-false}"; then
    use_genesis_ncu=1
  fi

  if [[ ! -f "${root}/MLP_NN/v1.5/predict_v15.py" ]]; then
    if ! command -v git >/dev/null 2>&1; then
      echo "ERROR: git is required to fetch PerfTools for GPU MLP estimation" >&2
      return 1
    fi

    mkdir -p "$(dirname "$root")"
    echo "Fetching PerfTools for GPU MLP estimation: ${repo} (${ref})"
    git clone --depth 1 "$repo" "$root"
    if [[ "$ref" != "main" && "$ref" != "master" ]]; then
      git -C "$root" fetch --depth 1 origin "$ref" || true
      git -C "$root" checkout "$ref"
    fi
  fi

  export BK_GPU_MLP_PERFTOOLS_ROOT="$root"
  export BK_GPU_MLP_OUTPUT_DIR="${BK_GPU_MLP_OUTPUT_DIR:-results/estimation_artifacts/gpu_kernel_mlp_v15}"

  echo "GPU MLP estimator root: ${BK_GPU_MLP_PERFTOOLS_ROOT}"
  if [[ "$use_genesis_ncu" -eq 1 ]]; then
    export BK_GPU_MLP_ARTIFACT_MODE="${BK_GPU_MLP_ARTIFACT_MODE:-ncu}"
    echo "GPU MLP estimator artifact mode: ${BK_GPU_MLP_ARTIFACT_MODE}"
  elif [[ "$use_qws_example" -eq 1 ]]; then
    input_csv="${BK_GPU_MLP_INPUT_CSV:-${root}/MLP_NN/examples/example_input_mixed-src_20kernels.csv}"
    if [[ ! -f "$input_csv" ]]; then
      echo "ERROR: PerfTools GPU MLP input CSV not found: ${input_csv}" >&2
      return 1
    fi
    export BK_GPU_MLP_INPUT_CSV="$input_csv"
    export BK_GPU_MLP_ARTIFACT_MODE="${BK_GPU_MLP_ARTIFACT_MODE:-input}"
    echo "GPU MLP estimator input CSV: ${BK_GPU_MLP_INPUT_CSV}"
  fi
}

# Check if the application has an estimate script
if [[ ! -f "$estimate_script" ]]; then
  echo "WARNING: $estimate_script not found, skipping estimation"
  exit 0
fi

bk_estimation_prepare_gpu_mlp_perftools

# Run estimation for each result JSON
found=0
for json_file in results/result[0-9]*.json; do
  [[ ! -f "$json_file" ]] && continue
  found=1
  echo "Input result metadata for $json_file:"
  jq '{code, system, Exp, _server_uuid, _server_timestamp}' "$json_file" || true
  if [[ -f results/server_result_meta.json ]]; then
    echo "Available result metadata manifest:"
    jq . results/server_result_meta.json || true
  fi
  echo "Running estimation: $estimate_script $json_file"
  bash "$estimate_script" "$json_file"
done

if [[ "$found" -eq 0 ]]; then
  echo "WARNING: No result*.json found in results/, skipping estimation"
  exit 0
fi

# Confirm estimate output files
echo "Estimation complete. Estimate files:"
ls results/estimate*.json 2>/dev/null || echo "No estimate files generated"
