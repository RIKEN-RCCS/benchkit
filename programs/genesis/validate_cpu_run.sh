#!/bin/bash
# Validate completion and finite observations; numerical accuracy is tested
# separately with GENESIS's upstream regression tests and reference outputs.
set -euo pipefail
log="$1"
input="$2"
expected=$(awk -F= '/^[[:space:]]*nsteps[[:space:]]*=/ {gsub(/[[:space:]]/, "", $2); print $2; exit}' "$input")
[[ "$expected" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid GENESIS nsteps" >&2; exit 1; }
awk -v expected="$expected" '
    function finite(value, converted) {
        if (value !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eEdD][+-]?[0-9]+)?$/) return 0
        gsub(/[dD]/, "e", value)
        converted=tolower(sprintf("%g", value+0))
        return converted !~ /inf|nan/
    }
    /^INFO:[[:space:]]+STEP/ { columns=NF; next }
    /^INFO:/ && $2 ~ /^[0-9]+$/ {
        rows++
        if (!columns || NF != columns || $2+0 > expected) bad=1
        for (i=2; i<=NF; i++) if (!finite($i)) bad=1
        last=$2+0
    }
    /^[[:space:]]*dynamics[[:space:]]*=/ {
        if (finite($3) && $3+0 > 0) timing=1; else bad=1
    }
    /[Ee][Rr][Rr][Oo][Rr]|MPI_ABORT|NaN|Infinity/ { bad=1 }
    END { exit (!bad && rows && last == expected && timing) ? 0 : 1 }
' "$log" || { echo "GENESIS did not finish with finite observations and a positive dynamics time" >&2; exit 1; }
