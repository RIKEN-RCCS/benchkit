#!/bin/bash
# Capture file observations on the execution host; JSON queries belong to the sender.
set -Eeuo pipefail
export LC_ALL=C
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$ROOT/json_output.sh"
kind="" source_path="" reference="" references=""
while [ "$#" -gt 0 ]; do
  [ "$#" -ge 2 ] || exit 2
  case "$1" in
    --file) kind="file"; source_path=$2 ;;
    --directory) kind=directory; source_path=$2 ;;
    --expected-manifest) reference=$2 ;;
    --references-dir) references=$2 ;;
    *) exit 2 ;;
  esac
  shift 2
done
[ -n "$kind" ] && [ -n "$source_path" ] || exit 2
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
unavailable() {
  printf '{"collection_status":"unavailable","collection_error":"collection_failed","verification_status":"unavailable"}\n'
  exit 0
}
trap unavailable ERR
for tool in realpath stat find head sort sha256sum dd tee wc mkfifo cmp date awk tr cp mv; do
  command -v "$tool" >/dev/null || unavailable
done
started=$(date +%s.%N)
IFS= read -r -d '' root < <(realpath -ez -- "$source_path")
[ "$kind" != directory ] || [ -d "$root" ]

fingerprint() { stat -c '%d:%i:%f:%s:%y:%z' -- "$1"; }
# File names must survive JSON encoding without replacing invalid UTF-8 bytes.
utf8=$'^([\001-\177]|[\302-\337][\200-\277]|\340[\240-\277][\200-\277]|[\341-\354\356-\357][\200-\277][\200-\277]|\355[\200-\237][\200-\277]|\360[\220-\277][\200-\277][\200-\277]|[\361-\363][\200-\277][\200-\277][\200-\277]|\364[\200-\217][\200-\277][\200-\277])*$'
visit() {
  local path=$1 relative=$2 depth=$3 ancestors=$4 resolved info identity child name
  count=$((count + 1))
  [ "$count" -le 10000 ] && [ "$depth" -le 64 ]
  [[ "$relative" =~ $utf8 ]]
  IFS= read -r -d '' resolved < <(realpath -ez -- "$path")
  if [ "$kind" = directory ]; then
    [[ "$resolved" = "$root" || "$resolved" = "${root%/}/"* ]]
  fi
  info=$(fingerprint "$resolved")
  printf '%s\0' "$relative" "$resolved" "$(fingerprint "$path")" "$info" >> "$inventory"
  if [ -f "$resolved" ]; then
    printf '%s\0' "$relative" "$resolved" "$info" >> "$files"
  elif [ "$kind" = directory ] && [ -d "$resolved" ]; then
    identity=$(stat -c '%d:%i' -- "$resolved")
    [[ "$ancestors" != *"|$identity|"* ]]
    # Bound enumeration before sorting, including directories and ignored entries.
    set +e
    find -P "$resolved" -mindepth 1 -maxdepth 1 -print0 \
      | head -z -n "$((10001 - count))" > "$work/children.$depth"
    local statuses=("${PIPESTATUS[@]}")
    set -e
    [ "${statuses[1]}" -eq 0 ]
    [[ "${statuses[0]}" = 0 || "${statuses[0]}" = 141 ]]
    sort -z "$work/children.$depth" > "$work/sorted.$depth"
    while IFS= read -r -d '' child; do
      name=${child##*/}
      [ -z "$relative" ] || name="$relative/$name"
      visit "$child" "$name" "$((depth + 1))" "$ancestors|$identity|"
    done < "$work/sorted.$depth"
  else
    return 1
  fi
}
inventory_tree() {
  inventory=$1 files=$2 count=0
  : > "$inventory"; : > "$files"
  local relative=""
  [ "$kind" = directory ] || relative=input
  visit "$source_path" "$relative" 0 ""
  [ -s "$files" ]
}
inventory_tree "$work/before" "$work/files"
printf '{"schema_version":1,"kind":"%s","files":[' "$kind" > "$work/manifest"
separator="" total=0 file_count=0
mkfifo "$work/hash-stream"
while IFS= read -r -d '' relative && IFS= read -r -d '' path && IFS= read -r -d '' info; do
  [ -f "$path" ] && [ ! -L "$path" ] && [ "$(fingerprint "$path")" = "$info" ]
  size=$(stat -c %s -- "$path")
  sha256sum < "$work/hash-stream" > "$work/hash" &
  hash_pid=$!
  # Stream once without a data copy. Count actual bytes and reject a short read.
  dd if="$path" iflag=nofollow,nonblock,count_bytes,fullblock bs=1048576 count="$((size + 1))" status=none \
    | tee "$work/hash-stream" | wc -c > "$work/size"
  wait "$hash_pid"
  [ "$(< "$work/size")" -eq "$size" ]
  [ -f "$path" ] && [ ! -L "$path" ] && [ "$(fingerprint "$path")" = "$info" ]
  read -r hash _ < "$work/hash"
  [[ "$hash" =~ ^[0-9a-f]{64}$ ]]
  printf '%s' "$separator" >> "$work/manifest"
  bk_json_object string path "$relative" string sha256 "$hash" json size_bytes "$size" >> "$work/manifest"
  separator=, total=$((total + size)) file_count=$((file_count + 1))
  [ "$(stat -c %s "$work/manifest")" -le 4194304 ]
done < "$work/files"
printf ']}' >> "$work/manifest"
[ "$(stat -c %s "$work/manifest")" -le 4194304 ]
inventory_tree "$work/after" "$work/after-files"
cmp -s "$work/before" "$work/after"

# An optional reference is a private, bounded companion, never embedded in public observations.
reference_id=""
capture_reference() (
  set -e
  IFS= read -r -d '' resolved < <(realpath -ez -- "$reference")
  [[ "$kind" != directory || ( "$resolved" != "$root" && "$resolved" != "${root%/}/"* ) ]]
  [ -f "$resolved" ] && [ ! -L "$resolved" ]
  info=$(fingerprint "$resolved")
  dd if="$resolved" of="$work/reference" iflag=nofollow,nonblock,count_bytes,fullblock \
    bs=65536 count=4194305 status=none
  [ "$(stat -c %s "$work/reference")" -le 4194304 ]
  [ "$(fingerprint "$resolved")" = "$info" ]
  [ -n "$references" ] && [ ! -L "$references" ]
  mkdir -p -- "$references"
  read -r hash _ < <(sha256sum < "$work/reference")
  temporary=$(mktemp "$references/.reference.XXXXXXXX")
  trap 'rm -f -- "$temporary"' EXIT
  cp -- "$work/reference" "$temporary"
  mv -f -- "$temporary" "$references/$hash"
  printf '%s' "$hash"
)
if [ -n "$reference" ]; then
  # Invoke a fresh shell so errexit remains active inside the capture operation.
  export -f fingerprint capture_reference
  export reference kind root work references
  reference_id=$(bash -e -c capture_reference 2>/dev/null) || reference_id=unavailable
fi
finished=$(date +%s.%N)
elapsed=$(awk -v start="$started" -v end="$finished" 'BEGIN {
  split(start,s,"."); split(end,e,"."); d=(e[1]-s[1])+(e[2]-s[2])/1000000000;
  if(d<0)exit 1; printf "%.6f",d;
}') || elapsed=""
printf '{"manifest":'; tr -d '\n' < "$work/manifest"
printf ',"size_bytes":%s,"file_count":%s,"collection_status":"recorded","verification_status":"declared"' "$total" "$file_count"
[ -z "$elapsed" ] || printf ',"collection_elapsed_seconds":%s,"collection_clock":"realtime"' "$elapsed"
[ -z "$reference_id" ] || { printf ',"reference_capture":'; bk_json_quote "$reference_id"; }
printf '}\n'
