#!/bin/bash
# Execution-side records: private NUL-delimited state, public JSON artifacts.
set -euo pipefail
export LC_ALL=C
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/json_output.sh"

fail() { echo 'Benchkit timing: unable to access stage artifact' >&2; exit 1; }
trap fail ERR
temporary=""
trap '[ -z "$temporary" ] || rm -f -- "$temporary"' EXIT

[ "${1:-}" = --results-dir ] && [ "$#" -ge 3 ] || exit 2
results=$2 command=$3
shift 3
mkdir -p -- "$results"
results=$(cd "$results" && pwd -P)
exec {lock}>> "$results/.workflow_timing.lock"
flock -x "$lock"
state="$results/.workflow_state"
[ ! -L "$state" ] && [ ! -L "$state/outputs" ] || fail
[ -d "$state" ] || mkdir -m 700 -- "$state"
mkdir -p -- "$state/outputs"

session="" exp="" stage="" tool=none profile="" output="" inputs=""
section="" token="" code="" started="" finished="" print_elapsed=0
outputs=() artifacts=()
if [ "$command" = finish ]; then
  [ "$#" -ge 2 ] || exit 2
  token=$1 code=$2; shift 2
fi
while [ "$#" -gt 0 ]; do
  if [ "$1" = --print-elapsed ]; then print_elapsed=1; shift; continue; fi
  [ "$#" -ge 2 ] || exit 2
  case "$1" in
    --session) session=$2 ;;
    --exp) exp=$2 ;;
    --stage) stage=$2 ;;
    --tool) tool=$2 ;;
    --profile) profile=$2 ;;
    --output) output=$2; outputs+=("$2") ;;
    --inputs) inputs=$2 ;;
    --section) section=$2 ;;
    --artifact) artifacts+=("$2") ;;
    --started) started=$2 ;;
    --finished) finished=$2 ;;
    *) exit 2 ;;
  esac
  shift 2
done

digest() { printf '%s' "$1" | sha256sum | cut -d ' ' -f 1; }
identifier() { od -An -N16 -tx1 /dev/urandom | tr -d ' \n'; }
output_key() {
  local absolute
  IFS= read -r -d '' absolute < <(realpath -msz -- "$1") || return 1
  digest "$absolute"
}
atomic() {
  local destination=$1
  temporary=$(mktemp "$state/write.XXXXXXXX")
  cat > "$temporary"
  mv -f -- "$temporary" "$destination"
  temporary=""
}
context() {
  bk_json_object string session_id "$session" | atomic "$results/.workflow_session.json"
}
load_scope() {
  [[ "$1" =~ ^[0-9a-f]{64}$ ]] || fail
  scope=$1 directory="$state/$1"
  [ ! -L "$directory" ] || fail
  [ -f "$directory/meta" ] && [ ! -L "$directory/meta" ] || fail
  mapfile -d '' -t meta < "$directory/meta"
  [ "${#meta[@]}" -eq 4 ] && [ "${meta[0]}" = workflow-v1 ] || fail
  [[ "${meta[3]}" = true || "${meta[3]}" = false ]] || fail
}
save_meta() { printf '%s\0' "${meta[@]}" | atomic "$directory/meta"; }
select_scope() {
  if [ -n "$output" ]; then
    local key mapped
    key=$(output_key "$output")
    mapped="$state/outputs/$(digest "$session")_$key"
    [ -f "$mapped" ] && [ ! -L "$mapped" ] || fail
    scope=$(< "$mapped")
  else
    [ -n "$exp" ] || fail
    scope=$(digest "$exp")
  fi
  load_scope "$scope"
  [ "${meta[1]}" = "$session" ] || fail
}
safe_artifact() {
  local resolved relative part
  IFS= read -r -d '' resolved < <(realpath -ez -- "$1") || return 1
  [[ "$resolved" = "$results/"* ]] && [ -f "$resolved" ] || return 1
  case "$resolved" in *.json|*.tgz) ;; *) return 1 ;; esac
  relative=${resolved#"$results/"}
  [[ "$relative" =~ ^[A-Za-z0-9_./-]+$ ]] || return 1
  local parts=()
  IFS=/ read -r -a parts <<< "$relative"
  for part in "${parts[@]}"; do [[ "$part" =~ ^[A-Za-z0-9_.-]+$ ]] || return 1; done
  printf 'results/%s\n' "$relative"
}
emit_document() {
  local id separator="" line name reference index
  local pairs=() names=()
  printf '{"schema_version":1,"kind":"workflow_stage_timing","producer":"benchkit",'
  printf '"session_id":'; bk_json_quote "${meta[1]}"
  printf ',"exp":'; bk_json_quote "${meta[2]}"
  printf ',"elapsed_clock":"realtime","elapsed_scope":"command"'
  [ "${meta[3]}" = false ] || printf ',"output_scoped":true'
  printf ',"stages":['
  [ -f "$directory/order" ] && [ ! -L "$directory/order" ] || return 1
  while IFS= read -r id; do
    [[ "$id" =~ ^[0-9a-f]{32}$ ]] || return 1
    [ -f "$directory/$id.json" ] && [ ! -L "$directory/$id.json" ] || return 1
    printf '%s' "$separator"; cat -- "$directory/$id.json"; separator=,
  done < "$directory/order"
  printf ']'
  if [ -f "$directory/inputs.jsonl" ]; then
    # These complete JSON records come from the input writer, not a JSON parser.
    printf ',"inputs":['; separator=""
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      printf '%s%s' "$separator" "$line"; separator=,
    done < "$directory/inputs.jsonl"
    printf ']'
  fi
  if [ -f "$directory/artifacts" ]; then
    mapfile -d '' -t pairs < "$directory/artifacts"
    [ $(( ${#pairs[@]} % 2 )) -eq 0 ] || return 1
    printf ',"section_artifacts":{'; separator=""
    for ((index=0; index<${#pairs[@]}; index+=2)); do
      name=${pairs[index]}
      local seen=0 previous
      for previous in "${names[@]}"; do [ "$name" != "$previous" ] || seen=1; done
      [ "$seen" -eq 0 ] || continue
      names+=("$name")
      printf '%s' "$separator"; bk_json_quote "$name"; printf ':['
      local item_separator="" j
      for ((j=0; j<${#pairs[@]}; j+=2)); do
        [ "${pairs[j]}" = "$name" ] || continue
        reference=${pairs[j+1]}
        printf '%s' "$item_separator"; bk_json_quote "$reference"; item_separator=,
      done
      printf ']'; separator=,
    done
    printf '}'
  fi
  printf '}\n'
}
publish() {
  temporary=$(mktemp "$state/write.XXXXXXXX")
  emit_document > "$temporary"
  mv -f -- "$temporary" "$results/workflow_timing_$scope.json"
  temporary=""
}

case "$command" in
  context)
    [ -n "$session" ] || exit 2
    context
    ;;
  start)
    [ -n "$session" ] && [ -n "$stage" ] || exit 2
    scope=$(digest "$exp")
    mapped=""
    if [ -n "$output" ]; then
      key=$(output_key "$output")
      mapped="$state/outputs/$(digest "$session")_$key"
      if [ "$stage" = benchmark ]; then scope=$(digest "$(identifier)"); else
        [ -f "$mapped" ] && [ ! -L "$mapped" ] || fail
        scope=$(< "$mapped")
      fi
    fi
    [[ "$scope" =~ ^[0-9a-f]{64}$ ]] || fail
    directory="$state/$scope"
    [ ! -L "$directory" ] || fail
    if [ -e "$directory/meta" ]; then
      load_scope "$scope"
    else
      meta=(workflow-v1 '' '' false)
    fi
    if [ "${meta[1]}" != "$session" ]; then
      rm -rf -- "$directory"
      mkdir -- "$directory"
      meta=(workflow-v1 "$session" "$exp" false)
      [ -z "$output" ] || meta[3]=true
      save_meta
      : > "$directory/order"
    fi
    if [ -n "$inputs" ]; then cp -- "$inputs" "$directory/inputs.jsonl"; fi
    id=$(identifier)
    [[ "$id" =~ ^[0-9a-f]{32}$ ]] || fail
    observed=$(date -u '+%Y-%m-%dT%H:%M:%S.%NZ')
    printf '%s\0' stage-v1 "$stage" "$tool" "$profile" "$observed" | atomic "$directory/$id.state"
    bk_json_object string id "$id" string stage "$stage" string tool "$tool" \
      string profile "$profile" string started_at "$observed" string status running | atomic "$directory/$id.json"
    printf '%s\n' "$id" >> "$directory/order"
    publish
    [ -z "$mapped" ] || printf '%s\n' "$scope" | atomic "$mapped"
    context
    echo "Benchkit timing: stage=$stage tool=$tool started_at=$observed" >&2
    printf 'workflow_timing_%s.json:%s\n' "$scope" "$id"
    ;;
  finish)
    [[ "$token" =~ ^workflow_timing_([0-9a-f]{64})\.json:([0-9a-f]{32})$ ]] || fail
    scope=${BASH_REMATCH[1]} id=${BASH_REMATCH[2]}
    [[ "$code" =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$code" -le 255 ] || fail
    load_scope "$scope"
    [ -f "$directory/$id.state" ] && [ ! -L "$directory/$id.state" ] || fail
    mapfile -d '' -t record < "$directory/$id.state"
    [ "${#record[@]}" -eq 5 ] && [ "${record[0]}" = stage-v1 ] || fail
    sample_pattern='^([0-9]{1,11}\.[0-9]{9})\|([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{9}Z)$'
    [[ "$started" =~ $sample_pattern ]] || fail
    start_seconds=${BASH_REMATCH[1]} start_at=${BASH_REMATCH[2]}
    [[ "$finished" =~ $sample_pattern ]] || fail
    end_seconds=${BASH_REMATCH[1]} end_at=${BASH_REMATCH[2]}
    elapsed=$(awk -v start="$start_seconds" -v end="$end_seconds" 'BEGIN {
      split(start, s, "."); split(end, e, ".");
      seconds = (e[1] - s[1]) + (e[2] - s[2]) / 1000000000;
      if (seconds < 0) exit 1; printf "%.9f", seconds;
    }')
    status=completed; [ "$code" -eq 0 ] || status=failed
    bk_json_object string id "$id" string stage "${record[1]}" string tool "${record[2]}" \
      string profile "${record[3]}" string started_at "${record[4]}" \
      string command_started_at "$start_at" string finished_at "$end_at" \
      json elapsed_seconds "$elapsed" json exit_code "$code" string status "$status" | atomic "$directory/$id.json"
    publish
    rm -- "$directory/$id.state"
    echo "Benchkit timing: stage=${record[1]} tool=${record[2]} finished_at=$end_at elapsed_seconds=$elapsed status=$status exit_code=$code" >&2
    [ "$print_elapsed" -eq 0 ] || printf '%s\n' "$elapsed"
    ;;
  bind)
    [ -n "$session" ] && [ -n "$exp" ] && [ "${#outputs[@]}" -gt 0 ] || exit 2
    scopes=()
    for output in "${outputs[@]}"; do
      select_scope
      [[ -z "${meta[2]}" || "${meta[2]}" = "$exp" ]] || fail
      scopes+=("$scope")
    done
    for scope in "${scopes[@]}"; do
      load_scope "$scope"; meta[2]=$exp; save_meta; publish
    done
    ;;
  workspace|register)
    [ -n "$session" ] || exit 2
    select_scope
    if [ "$command" = workspace ]; then
      mktemp -d "$results/profile_XXXXXXXXXXXX"
    else
      [ "${#artifacts[@]}" -gt 0 ] || exit 2
      additions=() pairs=()
      for artifact in "${artifacts[@]}"; do additions+=("$(safe_artifact "$artifact")"); done
      [ ! -f "$directory/artifacts" ] || mapfile -d '' -t pairs < "$directory/artifacts"
      [ $(( ${#pairs[@]} % 2 )) -eq 0 ] || fail
      if [ -n "$section" ]; then
        for ((i=0; i<${#pairs[@]}; i+=2)); do
          if [[ -z "${pairs[i]}" && "${pairs[i+1]}" = *.json ]]; then additions+=("${pairs[i+1]}"); fi
        done
      fi
      for artifact in "${additions[@]}"; do
        found=0
        for ((i=0; i<${#pairs[@]}; i+=2)); do
          [[ "${pairs[i]}" != "$section" || "${pairs[i+1]}" != "$artifact" ]] || found=1
        done
        [ "$found" -ne 0 ] || pairs+=("$section" "$artifact")
      done
      printf '%s\0' "${pairs[@]}" | atomic "$directory/artifacts"
      publish
    fi
    ;;
  *) exit 2 ;;
esac
