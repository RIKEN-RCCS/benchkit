#!/bin/bash
# Independent test scenarios; each selected part owns its temporary fixtures.
shell_test_parts() {
  case "${1##*/}" in
    test_bk_profiler.sh) printf '%s\n' fapp-basic fapp-detailed ncu-failures ;;
    test_bk_run.sh) printf '%s\n' 0 1 2 3 4 5 6 7 ;;
    test_bk_input_info.sh) printf '%s\n' declarations verification directory manifest-0 manifest-1 manifest-2 manifest-3 ;;
    test_build_cache.sh) printf '%s\n' cache git-tools ;;
    *) return 1 ;;
  esac
}

shell_test_parts_init() {
  local script="$1" selected="${2:-all}" part
  local parts
  parts=$(shell_test_parts "$script") || exit 2
  case "$selected" in
    --list-parts) printf '%s\n' "$parts"; exit 0 ;;
    all)
      while IFS= read -r part; do bash "$script" "$part"; done <<< "$parts"
      exit 0
      ;;
  esac
  while IFS= read -r part; do
    if [ "$selected" = "$part" ]; then
      TEST_PART="$selected"
      return 0
    fi
  done <<< "$parts"
  echo "Unknown shell test part: $selected" >&2
  exit 2
}
