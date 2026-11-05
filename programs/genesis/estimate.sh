#!/bin/bash
# estimate.sh — GENESIS estimation entrypoint.

source scripts/estimation/common.sh

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

genesis_estimation_assumptions() {
  "${BK_GPU_LIGHTGBM_PYTHON:-${BK_GPU_MLP_PYTHON:-python3}}" - "$1" "$BK_BENCHKIT_ROOT/scripts/estimation" 3<<< "${2:-null}" <<'PYNOTES'
import json, math, sys
sys.path.insert(0, sys.argv[2])
from gpu_profile_identity import profile_identity
result = json.load(open(sys.argv[1]))
sections = {s['name']: s for s in (result.get('fom_breakdown') or {}).get('sections', [])}
keys = ('pme_real_wait', 'pme_real_inter', 'pme_real_intra')
values = [sections.get(k, {}).get('time') for k in keys]
valid = all(isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0 for v in values)
fractions = dict(zip(keys, [v / sum(values) for v in values])) if valid and sum(values) > 0 else None
models = []
for section in (json.load(open(3)) or {}).get('sections', []):
    for candidate in section.get('candidate_estimates', []):
        identity = profile_identity(candidate)
        if identity is not None:
            models.append(dict(section=section['name'], **identity))
print(json.dumps(dict(genesis=dict(pme_real_partition=dict(fractions=fractions,
    basis='fractions_of_recorded_section_times' if fractions else 'unknown',
    note='PME wait/inter/intra partitioning is an assumption, not independent measured timers.'),
    gpu_specifications=models,
    note='GPU specification substitution and representative PID accuracy are unvalidated; missing identity is not inferred.')), allow_nan=False))
PYNOTES
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  genesis_declare_estimation_layout
  bk_estimation_apply_declared_defaults
  BK_ESTIMATION_PACKAGE="${BK_ESTIMATION_PACKAGE:-$BK_ESTIMATION_FUTURE_PACKAGE}"
  return 0 2>/dev/null || exit 0
fi

genesis_declare_estimation_layout
bk_estimation_run_sections "$1" "${BK_GENESIS_ESTIMATE_OUTPUT_INDEX:-0}" \
  genesis_estimation_assumptions GENESIS recorded
