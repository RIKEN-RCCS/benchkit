#!/bin/bash
# Finalize observations and attach scoped inputs without changing execution artifacts.
set -euo pipefail
export LC_ALL=C
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
[ "${1:-}" = --results-dir ] && [ "$#" -eq 2 ] || exit 2
results=$2
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
trap 'echo "Benchkit input: unable to assemble input observations" >&2' ERR
printf '{"schema_version":1,"inputs":[]}' > "$work/info"
info_file=${BK_INPUT_INFO_FILE:-$results/input_info.json}
if [ -f "$info_file" ]; then
  jq -ces 'if length == 1 and (.[0] | type) == "object" then .[0] else error("invalid input info") end' \
    "$info_file" > "$work/info"
fi
bash "$ROOT/workflow_timing.sh" --results-dir "$results" inputs > "$work/scoped"
jq -c --slurpfile scoped "$work/scoped" '(.inputs // []) + $scoped[0] | .[]' \
  "$work/info" > "$work/items"
: > "$work/normalized"

canonical() {
  # Match the existing ASCII, sorted, compact manifest encoding, including DEL.
  jq -acjS -L "$ROOT" 'include "input_manifest"; manifest' "$1" | sed $'s/\x7f/\\\\u007f/g'
}
digest() { sha256sum < "$1" | cut -d ' ' -f 1; }
finalize() {
  jq -c '.observation_capture' "$work/item" > "$work/capture"
  jq -c 'del(.observation_capture,.manifest,.manifest_digest,.content_digest,.sha256,.size_bytes,
    .file_count,.collection_elapsed_seconds,.collection_error,.reference_error,.reference_manifest_digest) |
    .collection_status="unavailable" | .collection_error="collection_failed" | .verification_status="unavailable"' \
    "$work/item" > "$work/base"
  if ! jq -e '.collection_status == "recorded"' "$work/capture" >/dev/null; then
    cat "$work/base"; return
  fi
  jq '.manifest' "$work/capture" > "$work/raw"
  if ! canonical "$work/raw" > "$work/manifest" 2>/dev/null || [ "$(stat -c %s "$work/manifest")" -gt 4194304 ]; then
    cat "$work/base"; return
  fi
  manifest_digest="sha256:$(digest "$work/manifest")"
  jq -c --slurpfile capture "$work/capture" --slurpfile manifest "$work/manifest" --arg digest "$manifest_digest" '
    $manifest[0] as $m | del(.collection_error) |
    . + {manifest:$m,manifest_digest:$digest,collection_status:"recorded",verification_status:"declared",
      size_bytes:([$m.files[].size_bytes]|add),file_count:($m.files|length),
      content_digest:(if $m.kind == "file" then "sha256:"+$m.files[0].sha256 else $digest end)} |
    if $m.kind == "file" then .sha256=$m.files[0].sha256 else . end |
    if ($capture[0].collection_elapsed_seconds|type) == "number" then
      .collection_elapsed_seconds=$capture[0].collection_elapsed_seconds | .collection_clock="realtime" else . end |
    if (.dataset_version // "") == "" then .dataset_version=.content_digest else . end' \
    "$work/base" > "$work/observed"
  reference=$(jq -r '.reference_capture // empty' "$work/capture")
  if [ -n "$reference" ]; then
    reference_file="$results/.input_references/$reference"
    valid=false
    if [[ "$reference" =~ ^[0-9a-f]{64}$ ]] && [ ! -L "$results/.input_references" ] \
        && [ -f "$reference_file" ] && [ ! -L "$reference_file" ] \
        && [ "$(stat -c %s "$reference_file")" -le 4194304 ]; then
      if [ "$(digest "$reference_file")" = "$reference" ] && \
          jq -nce --stream -L "$ROOT" 'include "input_manifest"; strict_document | manifest' \
            "$reference_file" > "$work/reference-raw" 2>/dev/null && \
          canonical "$work/reference-raw" > "$work/reference" 2>/dev/null && \
          jq -e --slurpfile actual "$work/manifest" '.kind == $actual[0].kind' "$work/reference" >/dev/null; then
        valid=true
      fi
    fi
    if [ "$valid" = true ]; then
      status=mismatch
      if cmp -s "$work/reference" "$work/manifest"; then status=verified; fi
      jq -c --arg status "$status" --arg digest "sha256:$(digest "$work/reference")" \
        '.verification_status=$status | .reference_manifest_digest=$digest' "$work/observed"
    else
      jq -c '.verification_status="unavailable" | .reference_error="invalid_or_unavailable"' "$work/observed"
    fi
  else
    cat "$work/observed"
  fi
}
while IFS= read -r item; do
  printf '%s\n' "$item" > "$work/item"
  if jq -e 'has("observation_capture")' "$work/item" >/dev/null; then
    finalize >> "$work/normalized"
  else
    cat "$work/item" >> "$work/normalized"
  fi
done < "$work/items"
jq -c --slurpfile items "$work/normalized" '.inputs=($items |
  reduce .[] as $item ([]; if index($item) == null then . + [$item] else . end))' "$work/info"
