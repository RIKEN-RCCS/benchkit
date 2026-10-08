#!/bin/bash
set -euo pipefail

output="${1:-results/node_status_snapshot_run.json}"
capture="${output}.capture"
[ -f "$capture" ] || exit 0
temporary=$(mktemp "${output}.tmp.XXXXXX")
trap 'rm -f "$temporary"' EXIT
jq -se -f "$(dirname "${BASH_SOURCE[0]}")/node_status_snapshot.jq" "$capture" > "$temporary"
mv "$temporary" "$output"
