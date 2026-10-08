#!/bin/bash
# Sender-side JSON queries for execution artifacts; not used on compute nodes.
set -euo pipefail
[ "${1:-}" = --results-dir ] && [ "$#" -ge 3 ] || exit 2
results=$2 command=$3 exp="" destination=""
shift 3
while [ "$#" -gt 0 ]; do
  [ "$#" -ge 2 ] || exit 2
  case "$1" in --exp) exp=$2 ;; --destination) destination=$2 ;; *) exit 2 ;; esac
  shift 2
done
if [ ! -d "$results" ]; then
  if [ "$command" = inputs ]; then printf '[]\n'; exit 0; fi
  [ "$command" = manifest ] || exit 1
  printf '{"schema_version":1,"observations":[]}\n'
  exit 0
fi
results=$(cd "$results" && pwd -P)
exec {lock}>> "$results/.workflow_timing.lock"
flock -x "$lock"
session=""
if [ -f "$results/.workflow_session.json" ]; then
  session=$(jq -er '.session_id | strings' "$results/.workflow_session.json")
fi
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
documents="$work/documents.jsonl"
: > "$documents"
if [ -n "$session" ]; then
  for path in "$results"/workflow_timing_*.json; do
    [ -f "$path" ] && [ ! -L "$path" ] || continue
    filename=${path##*/}
    [[ "$filename" =~ ^workflow_timing_[0-9a-f]{64}\.json$ ]] || continue
    if ! jq -cs --arg session "$session" --arg filename "$filename" '
      if length != 1 then error("invalid document count") else .[0] end |
      [select(.session_id == $session and .kind == "workflow_stage_timing" and .schema_version == 1) |
      select((.output_scoped | not) or (.exp | type == "string" and length > 0)) |
      if (.stages | type) != "array" then error("invalid stages") else . end |
      if all(.stages[]; type == "object" and (.status | type == "string")) then .
      else error("invalid stage status") end |
      . + {filename: $filename}] | .[]
    ' "$path" > "$work/document" 2>/dev/null; then
      echo 'Benchkit timing: skipped invalid stage artifact' >&2
      continue
    fi
    cat "$work/document" >> "$documents"
  done
fi

safe_artifact() {
  local reference=$1 resolved part
  [[ "$reference" = results/* ]] || return 1
  [[ "$reference" =~ ^[A-Za-z0-9_./-]+$ ]] || return 1
  local parts=()
  IFS=/ read -r -a parts <<< "$reference"
  for part in "${parts[@]}"; do
    [[ "$part" =~ ^[A-Za-z0-9_.-]+$ && "$part" != . && "$part" != .. ]] || return 1
  done
  case "$reference" in *.json|*.tgz) ;; *) return 1 ;; esac
  resolved=$(realpath -e -- "$results/${reference#results/}")
  [[ "$resolved" = "$results/"* ]] && [ -f "$resolved" ]
}
case "$command" in
  inputs)
    jq -cn --slurpfile documents "$documents" '[ $documents[] |
      select((.exp | type) == "string" and .exp != "") |
      select((.inputs | type) == "array") |
      .exp as $exp | .inputs[]? | select(type == "object") | . + {result_exp:$exp} ] | unique'
    ;;
  manifest)
    jq -n --slurpfile documents "$documents" '{schema_version:1, observations: [ $documents[] |
      {id: (.filename | rtrimstr(".json")), kind:"workflow-stage-timing", producer:"benchkit",
       format:"workflow_stage_timing/v1", artifact:{type:"file_reference",path:("results/"+.filename)},
       summary:{stage_count:(.stages|length),
         completed_count:([.stages[] | select(.status=="completed")]|length),
         failed_count:([.stages[] | select(.status=="failed")]|length),
         unfinished_count:([.stages[] | select(.status=="running")]|length)}} +
      (if (.exp // "") != "" then {result_exp:.exp} else {} end)]}'
    ;;
  has-profiles)
    jq -nr --slurpfile documents "$documents" '
      if any($documents[]; .output_scoped) then any($documents[].stages[]; .stage=="collect") else empty end'
    ;;
  publish-primary)
    [[ "$destination" =~ ^padata[0-9]+\.tgz$ ]] || exit 1
    scoped=$(jq -cn --slurpfile documents "$documents" --arg exp "$exp" \
      '[$documents[] | select(.exp == $exp and $exp != "") | del(.inputs)]')
    jq -e 'any(.[]; .output_scoped)' <<< "$scoped" >/dev/null || exit 0
    archives=$(jq -c '[.[].section_artifacts[""][]? | select(endswith(".tgz"))]' <<< "$scoped")
    rm -f -- "$results/$destination"
    count=$(jq length <<< "$archives")
    if [ "$count" -eq 1 ]; then
      reference=$(jq -r '.[0]' <<< "$archives")
      safe_artifact "$reference"
      temporary=$(mktemp "$results/.archive.XXXXXXXX")
      trap 'rm -f -- "$temporary"; rm -rf -- "$work"' EXIT
      cp -- "$results/${reference#results/}" "$temporary"
      mv -f -- "$temporary" "$results/$destination"
    elif [ "$count" -gt 1 ]; then
      echo 'Benchkit profile: multiple primary archives; use named sections' >&2
    fi
    ;;
  enrich-sections)
    sections=$(jq -ce 'if type == "array" then . else error("invalid sections") end')
    enriched=$(jq -cn --argjson sections "$sections" --slurpfile documents "$documents" --arg exp "$exp" '
      $sections | map(. as $section |
        [ $documents[] | select(.exp == $exp and $exp != "") | .section_artifacts[$section.name][]? ] |
        sort_by(endswith(".tgz") | not) as $managed |
        reduce $managed[] as $path ($section;
          if any(.artifacts[]?; .path == $path) then . else
            .artifacts = ((.artifacts // []) + [{type:"file_reference",path:$path}]) end))')
    # Only newly managed references require validation here; app references have their own contract.
    while IFS= read -r reference; do safe_artifact "$reference"; done < <(
      jq -nr --slurpfile documents "$documents" --argjson sections "$sections" --arg exp "$exp" '
        $sections[] as $section | $documents[] | select(.exp == $exp and $exp != "") |
        .section_artifacts[$section.name][]?')
    printf '%s\n' "$enriched"
    ;;
  *) exit 2 ;;
esac
