#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found; skipping QWS timing artifact test"
  exit 0
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/results"

source "${REPO_DIR}/programs/qws/parse_timing.sh"

cat > "${TMP_DIR}/qws_case0.log" <<'EOF'
etime for sovler =    1.23456000000000e-01 sec.
etime for sovler =    3.56000000000000e-01 sec.
print timing
    rank	func_id                         	   calls	    total(s)	  average(s)
       0	prec_s_                         	      10	2.405930e-02	2.405930e-03
       0	bicgstab_dd_mix_                	      10	3.560000e-01	3.560000e-02
       0	overlap_probe_window            	      20	1.250000e-02	6.250000e-04
end
EOF

test "$(qws_extract_fom_from_log "${TMP_DIR}/qws_case0.log")" = "0.356"
qws_write_timing_artifact "${TMP_DIR}/qws_case0.log" CASE0 "${TMP_DIR}/results/qws_timing_CASE0.json" 0.356

jq -e '
  .schema_version == 1 and
  .producer == "qws" and
  .kind == "qws_timing_observation" and
  .exp == "CASE0" and
  .source_log == "qws_case0.log" and
  .fom_seconds == 0.356 and
  .summary.timer_count == 3 and
  .summary.schema_record_count == 0 and
  .summary.has_timing_table == true and
  .summary.has_overlap_probe_schema == false and
  .timers[1].id == "bicgstab_dd_mix_" and
  .timers[1].calls == 10 and
  .timers[1].total_seconds == 0.356
' "${TMP_DIR}/results/qws_timing_CASE0.json" >/dev/null

cat > "${TMP_DIR}/qws_overlap.log" <<'EOF'
QWS_TIMER_SCHEMA version:qws-overlap-v1 target:overlap_probe conventional_timers:on probe_mode:coarse_phase unit:sec direction_order:xf,xb,yf,yb,zf,zb,tf,tb
QWS_TIMER_SCHEMA_SECTION id:bicgstab_dd_mix_ kind:parent aggregation:inclusive
QWS_TIMER_SCHEMA_SECTION id:bicgstab_dd_mix_ddd_d_ kind:compute aggregation:exclusive parent:bicgstab_dd_mix_
QWS_TIMER_SCHEMA_OVERLAP_WINDOW id:prec_ddd.sap.o.ddd_in_accum_addsub compute:ddd_in,accum_addsub comm:halo_recv active_rule:npe_direction_ne_1 group_model:max_active_directions send_wait:after_window
QWS_TIMER_SCHEMA_MEASUREMENT hidden_recv_completion:upper_bound_on_coalesced_or_calc_end active_directions:not_collapsed producer_aggregation:none
    rank	func_id                         	   calls	    total(s)	  average(s)
       0	bicgstab_dd_mix_                	      10	4.240000e-01	4.240000e-02
       0	overlap_probe_recv_pending_window	      12	2.400000e-02	2.000000e-03
end
EOF

qws_emit_timing_artifact_json "${TMP_DIR}/qws_overlap.log" CASE1 0.424 > "${TMP_DIR}/results/qws_timing_CASE1.json"

jq -e '
  .summary.timer_count == 2 and
  .summary.schema_record_count == 5 and
  .summary.has_overlap_probe_schema == true and
  .schema[0].record_type == "QWS_TIMER_SCHEMA" and
  .schema[0].fields.version == "qws-overlap-v1" and
  .schema[0].fields.target == "overlap_probe" and
  .schema[0].fields.probe_mode == "coarse_phase" and
  .schema[1].record_type == "QWS_TIMER_SCHEMA_SECTION" and
  .schema[1].fields.id == "bicgstab_dd_mix_" and
  .schema[3].record_type == "QWS_TIMER_SCHEMA_OVERLAP_WINDOW" and
  .schema[3].fields.compute == "ddd_in,accum_addsub" and
  .schema[4].record_type == "QWS_TIMER_SCHEMA_MEASUREMENT"
' "${TMP_DIR}/results/qws_timing_CASE1.json" >/dev/null

echo "QWS timing artifact test passed"
