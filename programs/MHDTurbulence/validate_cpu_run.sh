#!/bin/bash
# Completion and finite diagnostics, not reference-based numerical validation.
set -euo pipefail
log="$1"
diagnostics="$2"
config="$3"
end_time=$(awk -F= '/::[[:space:]]*timemax[[:space:]]*=/ {v=$2; sub(/!.*/, "", v); gsub(/[dD]/,"e",v); print v+0; exit}' "$config")
max_steps=$(awk -F= '/::[[:space:]]*nhymax[[:space:]]*=/ {v=$2; sub(/!.*/, "", v); print v+0; exit}' "$config")
awk -v target="$end_time" -v limit="$max_steps" '
function finite(v, s) {
    if (v !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eEdD][+-]?[0-9]+)?$/) return 0
    gsub(/[dD]/,"e",v); s=tolower(sprintf("%g",v+0)); return s !~ /inf|nan/
}
/total step, final dt, final time:/ {
    sub(/^.*time:/, ""); if (NF == 2) { record=$0; if (getline <= 0) bad=1; $0=record " " $0 }
    if (NF != 3 || !finite($1) || !finite($2) || !finite($3) || $1 < 1 || $1 > limit || $2 <= 0 || $3 <= target) bad=1; final=1
}
/sim time \[s\]:/ {if (!finite($4) || $4 <= 0) bad=1; timing=1}
/time\/count\/cell/ {if (!finite($2) || $2 <= 0) bad=1; fom=1}
/program has been finished/ {finished=1}
/[Nn][Aa][Nn]|Infinity|MPI_ABORT|[Ee][Rr][Rr][Oo][Rr]/ {bad=1}
END {exit !(target > 0 && limit > 0 && final && timing && fom && finished && !bad)}
' "$log" || { echo "MHD completion check failed" >&2; exit 1; }
awk -v target="$end_time" '
function finite(v, s) {
    if (v !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eEdD][+-]?[0-9]+)?$/) return 0
    gsub(/[dD]/,"e",v); s=tolower(sprintf("%g",v+0)); return s !~ /inf|nan/
}
/^[[:space:]]*#/ || NF == 0 {next}
{rows++; if (NF != 4) bad=1; for(i=1;i<=NF;i++) if(!finite($i)) bad=1; last=$1; if($3 < 0 || $4 <= 0) bad=1}
END {exit !(rows >= 2 && last > target && !bad)}
' "$diagnostics" || { echo "MHD finite diagnostics check failed" >&2; exit 1; }
