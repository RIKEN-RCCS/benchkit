#!/bin/bash
# Collect invocation-local MPI rank-zero logs; state is data, never shell code.
set -euo pipefail
export LC_ALL=C

max_entries=10000
max_bytes=$((256 * 1024 * 1024))
command="${1:-}"
[ "$#" -gt 0 ] && shift
state="" log=""
while [ "$#" -gt 0 ]; do
  [ "$#" -ge 2 ] || exit 2
  case "$1" in
    --state) state="$2" ;;
    --log) log="$2" ;;
    *) exit 2 ;;
  esac
  shift 2
done
[ -n "$state" ] && [ -n "$log" ] || exit 2
case "$command" in snapshot|collect) ;; *) exit 2 ;; esac
for tool in realpath mktemp rm find head sort stat dd sha256sum tail od tr cat mv; do
  command -v "$tool" >/dev/null || exit 1
done
case "$state" in /*) ;; *) state="${PWD}/${state}" ;; esac
log=$(realpath -ms -- "$log")
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
trap 'echo "Benchkit output: unable to collect invocation output" >&2' ERR

declare -A identities=() hashes=() endings=()
root="$PWD"
if [ "$command" = collect ]; then
  exec {input}< "$state"
  IFS= read -r -d '' format <&"$input"
  [ "$format" = rank-output-v1 ]
  IFS= read -r -d '' root <&"$input"
  [[ "$root" = /* ]]
  count=0
  while IFS= read -r -d '' path <&"$input"; do
    count=$((count + 1))
    [ "$count" -le "$max_entries" ]
    [[ "$path" = ./* && -z "${identities[$path]:-}" ]]
    IFS= read -r -d '' info <&"$input"
    IFS= read -r -d '' hash <&"$input"
    IFS= read -r -d '' ends_line <&"$input"
    [[ "$info" =~ ^[0-9]+:[0-9]+:[0-9]+: && "$hash" =~ ^[a-f0-9]{64}$ ]]
    [[ "$ends_line" = 0 || "$ends_line" = 1 ]]
    identities["$path"]="$info" hashes["$path"]="$hash" endings["$path"]="$ends_line"
  done
  # A final partial field is not an intact state record.
  [ -z "$path" ]
  exec {input}<&-
fi
cd -- "$root"

# Print directories as well as files to bound traversal, including ignored trees.
# Only output.* trees are traversed, at most five directory levels below root.
set +e
find -P . -mindepth 1 -maxdepth 6 -print0 \
  -type d ! -path './*/*' ! -name 'output.*' -prune \
  | head -z -n "$((max_entries + 1))" > "$work/entries"
statuses=("${PIPESTATUS[@]}")
set -e
[ "${statuses[1]}" -eq 0 ]
[[ "${statuses[0]}" = 0 || "${statuses[0]}" = 141 ]]
count=0
: > "$work/candidates"
while IFS= read -r -d '' path; do
  count=$((count + 1))
  [ "$count" -le "$max_entries" ]
  [[ "${path##*/}" =~ ^(stdout|stderr)\.[0-9]+\.0$ ]] || continue
  [ ! -L "$path" ] && [ -f "$path" ] || continue
  [ "$(realpath -ms -- "$path")" != "$log" ] || continue
  printf '%s\0' "$path" >> "$work/candidates"
done < "$work/entries"
sort -z "$work/candidates" > "$work/sorted"
printf '%s\0' rank-output-v1 "$root" > "$work/state"
: > "$work/combined"
remaining="$max_bytes"
while IFS= read -r -d '' path; do
  [ ! -L "$path" ] && [ -f "$path" ]
  info=$(stat -c '%d:%i:%s:%y:%z' -- "$path")
  IFS=: read -r device inode size _ <<< "$info"
  [ "$size" -le "$remaining" ]
  # O_NOFOLLOW/O_NONBLOCK avoid following a replaced symlink or blocking on a FIFO.
  dd if="$path" of="$work/data" iflag=nofollow,nonblock,count_bytes,fullblock \
    bs=65536 count="$((remaining + 1))" status=none
  [ ! -L "$path" ] && [ -f "$path" ]
  [ "$(stat -c '%d:%i:%s:%y:%z' -- "$path")" = "$info" ]
  [ "$(stat -c %s -- "$work/data")" -eq "$size" ]
  remaining=$((remaining - size))
  hash=$(sha256sum < "$work/data")
  hash="${hash%% *}"
  ends_line=0
  if [ "$size" -eq 0 ] || [ "$(tail -c 1 "$work/data" | od -An -tu1 | tr -d '[:space:]')" = 10 ]; then
    ends_line=1
  fi
  if [ "$command" = snapshot ]; then
    printf '%s\0' "$path" "$info" "$hash" "$ends_line" >> "$work/state"
    continue
  fi
  previous="${identities[$path]:-}"
  if [ "$previous" = "$info" ] && [ "${hashes[$path]:-}" = "$hash" ]; then
    continue
  fi
  if [ -n "$previous" ]; then
    IFS=: read -r old_device old_inode old_size _ <<< "$previous"
    if [ "$device:$inode" = "$old_device:$old_inode" ] && [ "$size" -gt "$old_size" ]; then
      prefix=$(head -c "$old_size" "$work/data" | sha256sum)
      if [ "${prefix%% *}" = "${hashes[$path]}" ]; then
        tail -c "+$((old_size + 1))" "$work/data" > "$work/new"
        if [ "${endings[$path]}" = 0 ]; then
          # Do not complete a success pattern from an older unfinished line.
          tail -n +2 "$work/new" > "$work/data"
        else
          mv "$work/new" "$work/data"
        fi
      fi
    fi
  fi
  if [ -s "$work/data" ]; then
    printf '\n' >> "$work/combined"
    cat "$work/data" >> "$work/combined"
    [ "$ends_line" = 1 ] || printf '\n' >> "$work/combined"
  fi
done < "$work/sorted"
if [ "$command" = snapshot ]; then
  cat "$work/state" > "$state"
else
  # No invocation output is published until every selected file passes checks.
  cat "$work/combined" >> "$log"
fi
