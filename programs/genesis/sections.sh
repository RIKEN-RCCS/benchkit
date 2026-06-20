#!/bin/bash
# sections.sh — GENESIS section declarations and result metadata emission.

GENESIS_PME_OVERLAP_SECTION_MEMBERS="pme_real_wait,pme_real_inter,pme_real_intra,pme_recip"
GENESIS_DYNAMICS_SECTION_MEMBERS="pairlist,bond,angle,dihedral,pme_real_wait,pme_real_inter,pme_real_intra,pme_recip,integrator"

genesis_declare_estimation_layout() {
  bk_clear_estimation_defaults
  bk_clear_estimation_declarations
  bk_define_current_estimation_package weakscaling
  bk_define_future_estimation_package instrumented_app_sections_dummy
  bk_define_baseline_system "${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  bk_define_baseline_exp "${BK_ESTIMATION_BASELINE_EXP:-${BK_GENESIS_EXP:-p8}}"
  bk_define_future_system "${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  bk_define_current_target_nodes "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}"
  bk_define_future_target_nodes "${BK_ESTIMATION_FUTURE_TARGET_NODES:-1}"
  bk_declare_estimation_items --side future "$(cat <<EOF
section|pairlist|gpu_kernel_ensemble_average
section|bond|identity
section|angle|identity
section|dihedral|identity
section|pme_real_wait|identity
section|pme_real_inter|gpu_kernel_ensemble_average
section|pme_real_intra|gpu_kernel_ensemble_average
section|pme_recip|identity
section|integrator|identity
section|other|identity
overlap|$GENESIS_PME_OVERLAP_SECTION_MEMBERS|identity
overlap|$GENESIS_DYNAMICS_SECTION_MEMBERS|identity
EOF
)"
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
  done < <(genesis_extract_dynamics_sections "$log_file" "$fom")

  if [[ -n "$timing_items" ]]; then
    bk_emit_declared_timing_items --side future "$timing_items"
  fi
}

genesis_emit_estimation_data_from_log() {
  genesis_emit_section_metadata_from_log "$@"
}

genesis_emit_estimation_data_from_fom() {
  local fom="$1"
  genesis_emit_section_metadata_from_log "${BK_GENESIS_LOG_FILE:-results/log_p8.txt}" "$fom"
}
