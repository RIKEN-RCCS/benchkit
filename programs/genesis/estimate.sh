#!/bin/bash
# estimate.sh — GENESIS estimation entrypoint and run-time section metadata.

genesis_gpu_section_packages() {
  local raw=""

  if [[ -n "${BK_GENESIS_GPU_SECTION_PACKAGES:-}" ]]; then
    raw="$BK_GENESIS_GPU_SECTION_PACKAGES"
  elif [[ -n "${BK_GENESIS_GPU_SECTION_PACKAGE:-}" ]]; then
    raw="$BK_GENESIS_GPU_SECTION_PACKAGE"
  else
    raw="gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15"
  fi

  printf '%s\n' "$raw" |
    tr ',' '\n' |
    awk '{
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      if ($0 != "") print $0
    }'
}

genesis_primary_gpu_section_package() {
  genesis_gpu_section_packages | head -n 1
}

GENESIS_PME_OVERLAP_SECTION_MEMBERS="pme_real_wait,pme_real_inter,pme_real_intra,pme_recip"
GENESIS_DYNAMICS_SECTION_MEMBERS="pairlist,bond,angle,dihedral,pme_real_wait,pme_real_inter,pme_real_intra,pme_recip,integrator"

genesis_gpu_section_package_binding() {
  if [[ -n "${BK_GENESIS_GPU_SECTION_PACKAGE:-}" && -z "${BK_GENESIS_GPU_SECTION_PACKAGES:-}" ]]; then
    printf '%s\n' "$BK_GENESIS_GPU_SECTION_PACKAGE"
  else
    printf '%s\n' "gpu_kernel_ensemble_average"
  fi
}

genesis_declare_estimation_layout() {
  local gpu_section_package
  gpu_section_package=$(genesis_gpu_section_package_binding)

  bk_clear_estimation_defaults
  bk_clear_estimation_declarations
  bk_define_current_estimation_package weakscaling
  bk_define_future_estimation_package instrumented_app_sections_dummy
  bk_define_baseline_system "${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  bk_define_baseline_exp "${BK_ESTIMATION_BASELINE_EXP:-${BK_GENESIS_EXP:-p8}}"
  bk_define_future_system "${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  bk_define_current_target_nodes "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}"
  bk_define_future_target_nodes "${BK_ESTIMATION_FUTURE_TARGET_NODES:-1}"
  bk_declare_section --side future pairlist "$gpu_section_package"
  bk_declare_section --side future bond identity
  bk_declare_section --side future angle identity
  bk_declare_section --side future dihedral identity
  bk_declare_section --side future pme_real_wait identity
  bk_declare_section --side future pme_real_inter "$gpu_section_package"
  bk_declare_section --side future pme_real_intra "$gpu_section_package"
  bk_declare_section --side future pme_recip identity
  bk_declare_section --side future integrator identity
  bk_declare_section --side future other identity
  bk_declare_overlap --side future "$GENESIS_PME_OVERLAP_SECTION_MEMBERS" identity
  bk_declare_overlap --side future "$GENESIS_DYNAMICS_SECTION_MEMBERS" identity
}

genesis_extract_dynamics_sections() {
  local log_file="$1"
  local dynamics_time="$2"
  local pme_real_identity_fraction="${BK_GENESIS_PME_REAL_IDENTITY_FRACTION:-0.8}"
  local pme_real_inter_fraction="${BK_GENESIS_PME_REAL_INTER_FRACTION:-0.1}"
  local pme_real_intra_fraction="${BK_GENESIS_PME_REAL_INTRA_FRACTION:-0.1}"

  awk \
    -v dynamics="$dynamics_time" \
    -v pme_real_identity_fraction="$pme_real_identity_fraction" \
    -v pme_real_inter_fraction="$pme_real_inter_fraction" \
    -v pme_real_intra_fraction="$pme_real_intra_fraction" '
    function value(line, rest, parts) {
      rest = line
      sub(/^[^=]*=[[:space:]]*/, "", rest)
      split(rest, parts, /[[:space:]]+/)
      return parts[1] + 0
    }
    function min(a, b) { return a < b ? a : b }
    /^[[:space:]]*pairlist[[:space:]]*=/ { pairlist = value($0); found_pairlist = 1 }
    /^[[:space:]]*bond[[:space:]]*=/ { bond = value($0); found_bond = 1 }
    /^[[:space:]]*angle[[:space:]]*=/ { angle = value($0); found_angle = 1 }
    /^[[:space:]]*dihedral[[:space:]]*=/ { dihedral = value($0); found_dihedral = 1 }
    /^[[:space:]]*pme real[[:space:]]*=/ { pme_real = value($0); found_pme_real = 1 }
    /^[[:space:]]*pme recip[[:space:]]*=/ { pme_recip = value($0); found_pme_recip = 1 }
    /^[[:space:]]*integrator[[:space:]]*=/ { integrator = value($0); found_integrator = 1 }
    END {
      pme_real_wait = pme_real * pme_real_identity_fraction
      pme_real_inter = pme_real * pme_real_inter_fraction
      pme_real_intra = pme_real * pme_real_intra_fraction
      pme_real_total = pme_real_wait + pme_real_inter + pme_real_intra
      pme_overlap = min(pme_real_total, pme_recip)
      total = pairlist + bond + angle + dihedral + pme_real_total + pme_recip - pme_overlap + integrator
      if (total <= 0) {
        exit 1
      }
      other = dynamics - total
      dynamics_overlap = 0
      if (other < 0) {
        dynamics_overlap = -other
        other = 0
      }
      printf "section pairlist %.12g\n", pairlist
      printf "section bond %.12g\n", bond
      printf "section angle %.12g\n", angle
      printf "section dihedral %.12g\n", dihedral
      printf "section pme_real_wait %.12g\n", pme_real_wait
      printf "section pme_real_inter %.12g\n", pme_real_inter
      printf "section pme_real_intra %.12g\n", pme_real_intra
      printf "section pme_recip %.12g\n", pme_recip
      printf "section integrator %.12g\n", integrator
      printf "section other %.12g\n", other
      if (pme_overlap > 0) {
        printf "overlap pme_real_wait,pme_real_inter,pme_real_intra,pme_recip %.12g\n", pme_overlap
      }
      if (dynamics_overlap > 0) {
        printf "overlap pairlist,bond,angle,dihedral,pme_real_wait,pme_real_inter,pme_real_intra,pme_recip,integrator %.12g\n", dynamics_overlap
      }
      missing = 0
      missing += !found_pairlist
      missing += !found_bond
      missing += !found_angle
      missing += !found_dihedral
      missing += !found_pme_real
      missing += !found_pme_recip
      missing += !found_integrator
      if (missing > 0) {
        printf "GENESIS section extraction warning: %d expected dynamics sections were not found in log\n", missing > "/dev/stderr"
      }
    }
  ' "$log_file"
}

genesis_section_key() {
  printf '%s\n' "$1" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g'
}

genesis_artifact_file_exists() {
  local rel_path="$1"

  [[ -n "$rel_path" ]] || return 1
  if [[ -f "$rel_path" ]]; then
    return 0
  fi
  if [[ -n "${GENESIS_BENCHKIT_ROOT:-}" && -f "${GENESIS_BENCHKIT_ROOT}/${rel_path}" ]]; then
    return 0
  fi
  return 1
}

genesis_section_artifact_path() {
  local section_name="$1"
  local section_key
  local env_var
  local explicit_artifact
  local candidate

  section_key=$(genesis_section_key "$section_name")
  env_var="BK_GENESIS_SECTION_${section_key}_ARTIFACT"
  explicit_artifact="${!env_var:-}"
  if [[ -n "$explicit_artifact" ]]; then
    if genesis_artifact_file_exists "$explicit_artifact"; then
      printf '%s\n' "$explicit_artifact"
      return 0
    fi
    echo "GENESIS section artifact was requested but not found: ${env_var}=${explicit_artifact}" >&2
    return 1
  fi

  case "$section_name" in
    pairlist)
      for candidate in "results/padata_pairlist.tgz" "results/padata0.tgz"; do
        if genesis_artifact_file_exists "$candidate"; then
          printf '%s\n' "$candidate"
          return 0
        fi
      done
      ;;
    pme_real_inter)
      candidate="results/padata_inter.tgz"
      if genesis_artifact_file_exists "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
      ;;
    pme_real_intra)
      candidate="results/padata_intra.tgz"
      if genesis_artifact_file_exists "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
      ;;
    *)
      candidate="results/padata_${section_name}.tgz"
      if genesis_artifact_file_exists "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
      ;;
  esac

  return 1
}

genesis_emit_estimation_data_from_log() {
  local log_file="$1"
  local fom="$2"
  local item_kind
  local item_name
  local item_time
  local section_artifact=""

  if [[ ! -f "$log_file" ]]; then
    echo "Genesis timing log was not found: ${log_file}" >&2
    return 0
  fi

  while read -r item_kind item_name item_time; do
    [[ -n "$item_kind" && -n "$item_name" && -n "$item_time" ]] || continue
    section_artifact=""
    case "$item_kind" in
      section)
        case "$item_name" in
          pairlist|pme_real_inter|pme_real_intra)
            section_artifact=$(genesis_section_artifact_path "$item_name" || true)
            ;;
        esac
        bk_emit_declared_section --side future "$item_name" "$item_time" "$section_artifact"
        ;;
      overlap)
        bk_emit_declared_overlap --side future "$item_name" "$item_time"
        ;;
    esac
  done < <(genesis_extract_dynamics_sections "$log_file" "$fom")
}

genesis_emit_estimation_data_from_fom() {
  local fom="$1"
  genesis_emit_estimation_data_from_log "${BK_GENESIS_LOG_FILE:-results/log_p8.txt}" "$fom"
}

genesis_input_has_fom_breakdown() {
  local input_json="$1"

  jq -e '((.fom_breakdown.sections // []) | length) > 0' "$input_json" >/dev/null 2>&1
}

genesis_write_total_identity_breakdown_input() {
  local input_json="$1"
  local output_json="$2"

  jq '
    .fom_breakdown = {
      sections: [
        {
          name: "total",
          time: (.FOM | tonumber),
          estimation_package: "identity"
        }
      ],
      overlaps: []
    }
  ' "$input_json" > "$output_json"
}

genesis_mark_gpu_section_time_missing() {
  bk_estimation_set_applicability \
    "partially_applicable" \
    "" \
    '["app_gpu_section_time"]' \
    '["provide-app-side-gpu-section-time-to-enable-gpu-kernel-estimator-fom-composition"]'

  est_notes_json=$(jq -cn '{
    summary: "GENESIS GPU kernel estimator data may contain NCU sample ratios, but FOM composition used a total identity section because app-side GPU section time is not available yet.",
    gpu_kernel_estimation: "NCU sample predicted/source ratios must be applied to app-side GPU section time before they can contribute to FOM reconstruction."
  }')
}

source scripts/bk_functions.sh
source scripts/estimation/common.sh

BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-1.0}"
BK_GPU_MLP_ARTIFACT_MODE="${BK_GPU_MLP_ARTIFACT_MODE:-ncu}"
BK_GPU_MLP_SOURCE_GPU="${BK_GPU_MLP_SOURCE_GPU:-H100}"
BK_GPU_MLP_KERNEL_COUNT="${BK_GPU_MLP_KERNEL_COUNT:-20}"
BK_GPU_LIGHTGBM_ARTIFACT_MODE="${BK_GPU_LIGHTGBM_ARTIFACT_MODE:-ncu}"
BK_GPU_LIGHTGBM_SOURCE_GPU="${BK_GPU_LIGHTGBM_SOURCE_GPU:-${BK_GPU_MLP_SOURCE_GPU}}"
BK_GPU_KERNEL_ENSEMBLE_PACKAGES="${BK_GPU_KERNEL_ENSEMBLE_PACKAGES:-$(genesis_gpu_section_packages | paste -sd, -)}"
BK_GPU_KERNEL_SECTION_PAIRLIST_REGEX="${BK_GPU_KERNEL_SECTION_PAIRLIST_REGEX:-build_pairlist}"
BK_GPU_KERNEL_SECTION_PME_REAL_INTER_REGEX="${BK_GPU_KERNEL_SECTION_PME_REAL_INTER_REGEX:-force_inter_cell}"
BK_GPU_KERNEL_SECTION_PME_REAL_INTRA_REGEX="${BK_GPU_KERNEL_SECTION_PME_REAL_INTRA_REGEX:-force_intra_cell}"
export BK_GPU_MLP_ARTIFACT_MODE
export BK_GPU_MLP_SOURCE_GPU
export BK_GPU_MLP_KERNEL_COUNT
export BK_GPU_LIGHTGBM_ARTIFACT_MODE
export BK_GPU_LIGHTGBM_SOURCE_GPU
export BK_GPU_KERNEL_ENSEMBLE_PACKAGES
export BK_GPU_KERNEL_SECTION_PAIRLIST_REGEX
export BK_GPU_KERNEL_SECTION_PME_REAL_INTER_REGEX
export BK_GPU_KERNEL_SECTION_PME_REAL_INTRA_REGEX

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  genesis_declare_estimation_layout
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"
  return 0 2>/dev/null || exit 0
fi

genesis_run_single_estimate() {
  local input_json="$1"
  local output_index="$2"
  local package_input_json="$input_json"
  local synthetic_breakdown=0

  genesis_declare_estimation_layout
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"

  if ! genesis_input_has_fom_breakdown "$input_json"; then
    package_input_json=$(mktemp "${TMPDIR:-/tmp}/benchkit-genesis-total-breakdown.XXXXXX.json")
    genesis_write_total_identity_breakdown_input "$input_json" "$package_input_json"
    synthetic_breakdown=1
  fi

  BK_ESTIMATION_INPUT_JSON="$package_input_json"

  BK_ESTIMATION_SKIP_TOP_LEVEL_CURRENT_BREAKDOWN=true \
    bk_estimation_run_declared_future_package "$BK_ESTIMATION_INPUT_JSON"
  bk_estimation_run_recorded_current_with_weakscaling \
    "${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}" \
    "${BK_ESTIMATION_BASELINE_EXP:-}" \
    "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}" \
    "${BK_ESTIMATION_CURRENT_PACKAGE:-weakscaling}"
  est_current_fom="${est_current_bench_fom:-$est_current_fom}"
  est_current_fom_breakdown=""

  if [[ "$synthetic_breakdown" -eq 1 ]]; then
    genesis_mark_gpu_section_time_missing
    rm -f "$package_input_json"
  fi

  bk_estimation_write_output "results/estimate_${est_code}_${output_index}.json"
}

BK_ESTIMATION_INPUT_JSON="$1"
genesis_run_single_estimate "$BK_ESTIMATION_INPUT_JSON" "${BK_GENESIS_ESTIMATE_OUTPUT_INDEX:-0}"
