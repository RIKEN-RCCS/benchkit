#!/bin/bash
# parse_timing.sh — Extract GENESIS app-side section timings from a run log.

set -euo pipefail

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

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <genesis-log-file> <dynamics-fom-seconds>" >&2
    exit 2
  fi
  genesis_extract_dynamics_sections "$1" "$2"
fi
