#!/bin/bash
# estimate.sh — GENESIS estimation entrypoint.

source scripts/estimation/common.sh
source programs/genesis/section.sh

genesis_declare_estimation_layout() {
  GENESIS_PME_OVERLAP_SECTION_MEMBERS="pme_real_wait,pme_real_inter,pme_real_intra,pme_recip"
  GENESIS_DYNAMICS_SECTION_MEMBERS="pairlist,bond,angle,dihedral,pme_real_wait,pme_real_inter,pme_real_intra,pme_recip,integrator"
  bk_clear_estimation_defaults
  local method_version
  method_version=$(jq -er '.version | select(type == "string" and length > 0)' programs/genesis/estimate.metadata.json) || return
  bk_define_estimation_method_version "$method_version"
  bk_clear_estimation_declarations
  bk_define_current_estimation_package weakscaling
  bk_define_future_estimation_package instrumented_app_sections_dummy
  bk_define_baseline_system "${BK_ESTIMATION_BASELINE_SYSTEM:-Fugaku}"
  bk_define_baseline_exp "${BK_ESTIMATION_BASELINE_EXP:-${BK_GENESIS_EXP:-p8}}"
  bk_define_future_system "${BK_ESTIMATION_FUTURE_SYSTEM:-FugakuNEXT}"
  bk_define_current_target_nodes "${BK_ESTIMATION_CURRENT_TARGET_NODES:-1}"
  bk_define_future_target_nodes "${BK_ESTIMATION_FUTURE_TARGET_NODES:-1}"
  bk_declare_estimation_items --side future "$(cat <<EOF
section|pairlist|gpu_kernel_ensemble_average|gpu_counters
section|bond|identity
section|angle|identity
section|dihedral|identity
section|pme_real_wait|identity
section|pme_real_inter|gpu_kernel_ensemble_average|gpu_counters
section|pme_real_intra|gpu_kernel_ensemble_average|gpu_counters
section|pme_recip|identity
section|integrator|identity
section|other|identity
overlap|$GENESIS_PME_OVERLAP_SECTION_MEMBERS|identity
overlap|$GENESIS_DYNAMICS_SECTION_MEMBERS|identity
EOF
)"
}

BK_ESTIMATION_SECTION_DEFAULT_FACTOR="${BK_ESTIMATION_SECTION_DEFAULT_FACTOR:-1.0}"
BK_GENESIS_GPU_TARGET_GPU="${BK_GENESIS_GPU_TARGET_GPU:-GB200}"
bk_estimation_configure_gpu_kernel_defaults \
  H100 \
  "$BK_GENESIS_GPU_TARGET_GPU" \
  "" \
  20 \
  ncu
bk_estimation_configure_gpu_kernel_section_regexes "$(cat <<'EOF'
pairlist|build_pairlist
pme_real_inter|force_inter_cell
pme_real_intra|force_intra_cell
EOF
)"

genesis_record_estimation_assumptions() {
  local annotation
  annotation=$("${BK_GPU_LIGHTGBM_PYTHON:-${BK_GPU_MLP_PYTHON:-python3}}" - "$1" "$est_future_fom_breakdown" <<'PYNOTES'
import csv, json, math, sys
result = json.load(open(sys.argv[1]))
sections = {s['name']: s for s in (result.get('fom_breakdown') or {}).get('sections', [])}
keys = ('pme_real_wait', 'pme_real_inter', 'pme_real_intra')
values = [sections.get(k, {}).get('time') for k in keys]
valid = all(isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0 for v in values)
fractions = dict(zip(keys, [v / sum(values) for v in values])) if valid and sum(values) > 0 else None
models = []
for section in (json.loads(sys.argv[2] or '{}') or {}).get('sections', []):
    for candidate in section.get('candidate_estimates', []):
        metrics = candidate.get('metrics', {})
        source_gpus = metrics.get('source_gpus', [])
        if not source_gpus:
            continue
        observed = set()
        for artifact in candidate.get('artifacts', []):
            if artifact.get('kind') != 'gpu_lightgbm_input_csv':
                continue
            try:
                with open(artifact.get('path') or '', newline='') as handle:
                    observed.update(row['device__attribute_display_name'] for row in csv.DictReader(handle)
                                    if row.get('device__attribute_display_name') not in (None, '', 'nan'))
            except (OSError, csv.Error, UnicodeError):
                pass  # Missing physical identity must remain unknown.
        models.append(dict(section=section['name'], package=candidate.get('estimation_package'),
            observed_profile_gpu_names=sorted(observed), model_source_gpu_names=source_gpus,
            specification_mapping=('gh200_using_h100_specifications' if 'H100' in source_gpus
                and any('GH200' in name for name in observed) else 'unverified' if observed else 'unknown')))
print(json.dumps(dict(pme_real_partition=dict(fractions=fractions,
    basis='fractions_of_recorded_section_times' if fractions else 'unknown',
    note='PME wait/inter/intra partitioning is an assumption, not independent measured timers.'),
    gpu_specifications=models,
    note='GPU specification substitution and representative PID accuracy are unvalidated; missing identity is not inferred.'), allow_nan=False))
PYNOTES
  )
  est_assumptions_json=$(jq -c --argjson genesis "$annotation" '(. // {}) + {genesis:$genesis}' <<< "${est_assumptions_json:-null}")
}

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
  if ! bk_estimation_input_has_fom_breakdown "$input_json"; then
    package_input_json=$(mktemp "${TMPDIR:-/tmp}/benchkit-genesis-total-breakdown.XXXXXX.json")
    bk_estimation_write_total_identity_breakdown_input "$input_json" "$package_input_json"
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

  if [[ "$synthetic_breakdown" -eq 1 ]]; then
    bk_estimation_mark_gpu_section_time_missing "GENESIS"
    rm -f "$package_input_json"
  fi

  genesis_record_estimation_assumptions "$input_json"

  # est_code is populated by the common estimation reader.
  # shellcheck disable=SC2154
  bk_estimation_write_output "results/estimate_${est_code}_${output_index}.json"
}

BK_ESTIMATION_INPUT_JSON="$1"
genesis_run_single_estimate "$BK_ESTIMATION_INPUT_JSON" "${BK_GENESIS_ESTIMATE_OUTPUT_INDEX:-0}"
