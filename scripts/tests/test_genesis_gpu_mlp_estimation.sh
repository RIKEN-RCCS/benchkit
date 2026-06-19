#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "${SCRIPT_DIR}/../.." && pwd)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/programs" "${TMP_DIR}/scripts" "${TMP_DIR}/results"
cp -R "${REPO_DIR}/programs/genesis" "${TMP_DIR}/programs/genesis"
cp "${REPO_DIR}/scripts/bk_functions.sh" "${TMP_DIR}/scripts/bk_functions.sh"
cp -R "${REPO_DIR}/scripts/estimation" "${TMP_DIR}/scripts/estimation"
cp -R "${REPO_DIR}/scripts/result_server" "${TMP_DIR}/scripts/result_server"

pushd "${TMP_DIR}" >/dev/null
export BK_GPU_MLP_FETCH_PERFTOOLS=false
export BK_GPU_LIGHTGBM_FETCH_PERFTOOLS=false
source programs/genesis/estimate.sh
test "${BK_ESTIMATION_BASELINE_EXP}" = "p8"
test "${BK_ESTIMATION_BASELINE_SYSTEM}" = "Fugaku"
test "${BK_ESTIMATION_FUTURE_SYSTEM}" = "FugakuNEXT"
test "${BK_GPU_KERNEL_ENSEMBLE_PACKAGES}" = "gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15,gpu_kernel_mlp_v21,gpu_kernel_mlp_v40,gpu_kernel_mlp_v41"

cat > results/no_breakdown_input.json <<'EOF'
{
  "code": "genesis",
  "Exp": "p8",
  "system": "MiyabiG",
  "FOM": 50.5,
  "node_count": 1,
  "numproc_node": 8
}
EOF
! genesis_input_has_fom_breakdown results/no_breakdown_input.json
genesis_write_total_identity_breakdown_input results/no_breakdown_input.json results/total_breakdown_input.json
genesis_input_has_fom_breakdown results/total_breakdown_input.json
jq -e '
  .fom_breakdown.sections[0].name == "total" and
  .fom_breakdown.sections[0].time == 50.5 and
  .fom_breakdown.sections[0].estimation_package == "identity" and
  .fom_breakdown.overlaps == []
' results/total_breakdown_input.json >/dev/null

cat > results/log_p8.txt <<'EOF'
  total time      =      51.892
    setup         =       3.030
    dynamics      =      48.862
      energy      =      23.692
      integrator  =      15.567
      pairlist    =       3.755 (       3.618,       3.923)
  energy
    bond          =       0.074 (       0.067,       0.089)
    angle         =       0.505 (       0.471,       0.543)
    dihedral      =       1.373 (       1.283,       1.477)
    nonbond       =      22.568 (      20.941,      23.765)
      pme real    =      22.566 (      20.940,      23.763)
      pme recip   =       4.203 (       4.181,       4.235)
  integrator
    constraint    =       1.219 (       1.196,       1.270)
    update        =       4.611 (       4.456,       4.877)
    comm_coord    =       2.668 (       2.329,       2.914)
    comm_force    =      11.186 (       9.988,      12.805)
    comm_migrate  =       0.121 (       0.095,       0.140)
EOF

genesis_extract_dynamics_sections results/log_p8.txt 48.862 > results/genesis_sections.tsv
test "$(wc -l < results/genesis_sections.tsv)" = "11"
awk '
  $1 == "section" { sum += $3 }
  $1 == "overlap" { overlap += $3 }
  END {
    diff = (sum - overlap) - 48.862
    if (diff < 0) diff = -diff
    exit(diff < 0.000001 ? 0 : 1)
  }
' results/genesis_sections.tsv
grep -q '^section pairlist ' results/genesis_sections.tsv
grep -q '^section pme_real_wait ' results/genesis_sections.tsv
grep -q '^section pme_real_inter ' results/genesis_sections.tsv
grep -q '^section pme_real_intra ' results/genesis_sections.tsv
grep -q '^overlap pme_real_wait,pme_real_inter,pme_real_intra,pme_recip ' results/genesis_sections.tsv
grep -q '^section integrator ' results/genesis_sections.tsv
awk '$1 == "section" && $2 == "other" {
  diff = $3 - 5.022
  if (diff < 0) diff = -diff
  found = diff < 0.000001
}
END { exit(found ? 0 : 1) }' results/genesis_sections.tsv
awk '$1 == "section" && $2 == "pme_real_wait" {
  diff = $3 - 18.0528
  if (diff < 0) diff = -diff
  found = diff < 0.000001
}
END { exit(found ? 0 : 1) }' results/genesis_sections.tsv
awk '$1 == "section" && $2 == "pme_real_inter" {
  diff = $3 - 2.2566
  if (diff < 0) diff = -diff
  found = diff < 0.000001
}
END { exit(found ? 0 : 1) }' results/genesis_sections.tsv
awk '$1 == "section" && $2 == "pme_real_intra" {
  diff = $3 - 2.2566
  if (diff < 0) diff = -diff
  found = diff < 0.000001
}
END { exit(found ? 0 : 1) }' results/genesis_sections.tsv
awk '$1 == "overlap" && $2 == "pme_real_wait,pme_real_inter,pme_real_intra,pme_recip" {
  diff = $3 - 4.203
  if (diff < 0) diff = -diff
  found = diff < 0.000001
}
END { exit(found ? 0 : 1) }' results/genesis_sections.tsv

cat > results/log_p8_overlap.txt <<'EOF'
  total time      =     156.531
    setup         =       3.030
    dynamics      =     156.531
      energy      =     145.000
      integrator  =      14.947
      pairlist    =       6.824 (       6.800,       6.900)
  energy
    bond          =       0.213 (       0.200,       0.220)
    angle         =       0.514 (       0.500,       0.530)
    dihedral      =       1.338 (       1.300,       1.400)
    nonbond       =     139.975 (     139.900,     140.100)
      pme real    =     139.975 (     139.900,     140.100)
      pme recip   =       4.924 (       4.900,       5.000)
  integrator
    constraint    =       1.219 (       1.196,       1.270)
EOF

genesis_extract_dynamics_sections results/log_p8_overlap.txt 156.531 > results/genesis_overlap_sections.tsv
test "$(wc -l < results/genesis_overlap_sections.tsv)" = "12"
awk '
  $1 == "section" { sum += $3 }
  $1 == "overlap" { overlap += $3 }
  END {
    diff = (sum - overlap) - 156.531
    if (diff < 0) diff = -diff
    exit(diff < 0.000001 ? 0 : 1)
  }
' results/genesis_overlap_sections.tsv
awk '$1 == "section" && $2 == "other" { found = ($3 == 0) } END { exit(found ? 0 : 1) }' results/genesis_overlap_sections.tsv
awk '$1 == "overlap" {
  diff = $3 - 7.28
  if (diff < 0) diff = -diff
  found = ($2 == "pairlist,bond,angle,dihedral,pme_real_wait,pme_real_inter,pme_real_intra,pme_recip,integrator" && diff < 0.000001)
}
END { exit(found ? 0 : 1) }' results/genesis_overlap_sections.tsv

genesis_emit_estimation_data_from_log results/log_p8.txt 48.862 > results/sections_no_archive.result
test "$(grep -c '^SECTION:' results/sections_no_archive.result)" = "11"
grep -q '^SECTION:pairlist .* estimation_package:gpu_kernel_ensemble_average' results/sections_no_archive.result
grep -q '^SECTION:pme_real_wait .* estimation_package:identity' results/sections_no_archive.result
grep -q '^SECTION:pme_real_inter .* estimation_package:gpu_kernel_ensemble_average' results/sections_no_archive.result
grep -q '^SECTION:pme_real_intra .* estimation_package:gpu_kernel_ensemble_average' results/sections_no_archive.result
grep -q '^SECTION:overlap:pme_real_wait,pme_real_inter,pme_real_intra,pme_recip .* estimation_package:identity' results/sections_no_archive.result
grep -q '^SECTION:bond .* estimation_package:identity' results/sections_no_archive.result
grep -q '^SECTION:integrator .* estimation_package:identity' results/sections_no_archive.result
grep -q '^SECTION:other .* estimation_package:identity' results/sections_no_archive.result
! grep -q 'artifact:results/padata0.tgz' results/sections_no_archive.result

genesis_emit_estimation_data_from_log results/log_p8_overlap.txt 156.531 > results/sections_with_overlap.result
grep -q '^SECTION:overlap:pairlist,bond,angle,dihedral,pme_real_wait,pme_real_inter,pme_real_intra,pme_recip,integrator .* type:overlap members:pairlist,bond,angle,dihedral,pme_real_wait,pme_real_inter,pme_real_intra,pme_recip,integrator estimation_package:identity' results/sections_with_overlap.result

touch results/padata_pairlist.tgz
genesis_emit_estimation_data_from_log results/log_p8.txt 48.862 > results/sections_with_archive.result
grep -q '^SECTION:pairlist .* estimation_package:gpu_kernel_ensemble_average artifact:results/padata_pairlist.tgz' results/sections_with_archive.result
grep -q '^SECTION:pme_real_inter .* estimation_package:gpu_kernel_ensemble_average$' results/sections_with_archive.result
grep -q '^SECTION:pme_real_intra .* estimation_package:gpu_kernel_ensemble_average$' results/sections_with_archive.result

touch results/padata_inter.tgz
touch results/padata_intra.tgz
genesis_emit_estimation_data_from_log results/log_p8.txt 48.862 > results/sections_with_explicit_pme_real_archive.result
grep -q '^SECTION:pme_real_inter .* estimation_package:gpu_kernel_ensemble_average artifact:results/padata_inter.tgz' results/sections_with_explicit_pme_real_archive.result
grep -q '^SECTION:pme_real_intra .* estimation_package:gpu_kernel_ensemble_average artifact:results/padata_intra.tgz' results/sections_with_explicit_pme_real_archive.result

BK_GENESIS_GPU_SECTION_PACKAGE=gpu_kernel_mlp_v15 \
  bash -c 'source programs/genesis/estimate.sh; genesis_emit_estimation_data_from_log results/log_p8.txt 48.862' \
  > results/sections_with_mlp_archive.result
grep -q '^SECTION:pairlist .* estimation_package:gpu_kernel_mlp_v15 artifact:results/padata_pairlist.tgz' results/sections_with_mlp_archive.result

mkdir -p genesis_benchmark_input/npt/genesis2.0beta_3.5fs/apoa1
GENESIS_BENCHKIT_ROOT="$PWD" \
  bash -c 'source programs/genesis/estimate.sh; cd genesis_benchmark_input/npt/genesis2.0beta_3.5fs/apoa1; genesis_emit_estimation_data_from_log "$GENESIS_BENCHKIT_ROOT/results/log_p8.txt" 48.862' \
  > results/from_subdir.result
grep -q 'artifact:results/padata_pairlist.tgz' results/from_subdir.result
popd >/dev/null

echo "genesis gpu mlp estimation metadata test passed"
