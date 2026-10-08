#!/bin/bash
# Serialize session initialization across child shells without a JSON runtime.
set -euo pipefail

session="" kind="" info="" items=""
while [ "$#" -gt 0 ]; do
  [ "$#" -ge 2 ] || exit 2
  case "$1" in
    --session) session="$2" ;;
    --kind) kind="$2" ;;
    --info) info="$2" ;;
    --items) items="$2" ;;
    *) exit 2 ;;
  esac
  shift 2
done
[ -n "$session" ] && [ -n "$info" ] && [ -n "$items" ] || exit 2
case "$kind" in input|timing) ;; *) exit 2 ;; esac
directory=$(dirname -- "$info")
mkdir -p -- "$directory"
state="${directory}/.$(basename -- "$info").session"
case "$items" in /*) ;; *) items="${PWD}/${items}" ;; esac
exec {lock}<> "$state"
flock -x "$lock"
status=0
cmp -s -- "$state" <(printf '%s\0' shell-session-v1 "$session" "$items") || status=$?
case "$status" in
  0) exit 0 ;;
  1) ;;
  *) echo "Benchkit metadata: unable to read session state" >&2; exit 1 ;;
esac
rm -f -- "$info" "$items"
if [ "$kind" = timing ]; then
  rm -f -- "${directory}/.workflow_session.json"
fi
printf '%s\0' shell-session-v1 "$session" "$items" > "$state"
