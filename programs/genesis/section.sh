#!/bin/bash
# section.sh — GENESIS observation definitions and measured section emission.

source "${BK_BENCHKIT_ROOT}/scripts/estimation/section_artifacts.sh"
source "${BASH_SOURCE[0]%/*}/parse_timing.sh"
source "${BASH_SOURCE[0]%/*}/profile.sh"

genesis_declare_observation() {
  bk_clear_observation_definitions
  bk_define_observation_version "1"
  bk_define_section_time_collector genesis_extract_dynamics_sections
  bk_define_section_time_unit s
  bk_define_profile gpu_counters genesis_configure_ncu_profile
}

genesis_section_artifact_path() {
  local section_name="$1"

  bk_estimation_resolve_section_artifact \
    "BK_GENESIS_SECTION" \
    "${GENESIS_BENCHKIT_ROOT:-}" \
    "$section_name"
}

genesis_emit_section_metadata_from_log() {
  local log_file="$1"
  local fom="$2"
  local item_kind
  local item_name
  local item_time
  local section_artifact=""
  local timing_items=""

  bk_emit_observation_definition

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
        ;;
      overlap)
        section_artifact=""
        ;;
    esac

    if [[ -n "$timing_items" ]]; then
      timing_items="${timing_items}
${item_kind}|${item_name}|${item_time}|${section_artifact}"
    else
      timing_items="${item_kind}|${item_name}|${item_time}|${section_artifact}"
    fi
  done < <("$BK_SECTION_TIME_COLLECTOR" "$log_file" "$fom")

  if [[ -n "$timing_items" ]]; then
    while IFS='|' read -r item_kind item_name item_time section_artifact; do
      case "$item_kind" in
        section) bk_emit_section "$item_name" "$item_time" "" "$section_artifact" ;;
        overlap) bk_emit_overlap "$item_name" "$item_time" "" "$section_artifact" ;;
      esac
    done <<< "$timing_items"
  fi
}

genesis_emit_estimation_data_from_log() {
  genesis_emit_section_metadata_from_log "$@"
}

genesis_emit_estimation_data_from_fom() {
  local fom="$1"
  genesis_emit_section_metadata_from_log "${BK_GENESIS_LOG_FILE:-results/log_p8.txt}" "$fom"
}

genesis_declare_observation
