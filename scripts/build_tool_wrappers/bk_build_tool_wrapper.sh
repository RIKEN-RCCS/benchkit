#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "bk_build_tool_wrapper: missing tool name" >&2
  exit 127
fi

tool_name="$1"
shift

wrapper_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root="${BK_BENCHKIT_ROOT:-$(cd "${wrapper_dir}/../.." && pwd -P)}"
original_path="${PATH:-}"
path_without_wrapper=""

IFS=':' read -r -a path_entries <<< "$original_path"
for path_entry in "${path_entries[@]}"; do
  display_entry="$path_entry"
  if [ -z "$display_entry" ]; then
    display_entry="."
  fi

  entry_abs="$display_entry"
  if [ -d "$display_entry" ]; then
    entry_abs=$(cd "$display_entry" && pwd -P)
  fi

  if [ "$entry_abs" = "$wrapper_dir" ]; then
    continue
  fi

  if [ -z "$path_without_wrapper" ]; then
    path_without_wrapper="$path_entry"
  else
    path_without_wrapper="${path_without_wrapper}:$path_entry"
  fi
done

real_tool=$(PATH="$path_without_wrapper" command -v "$tool_name" 2>/dev/null || true)
if [ -z "$real_tool" ]; then
  echo "bk_build_tool_wrapper: ${tool_name} not found after removing ${wrapper_dir} from PATH" >&2
  exit 127
fi

if [ "${BK_BUILD_TOOL_WRAPPER_SNAPSHOT:-true}" != "false" ]; then
  (
    export PATH="$path_without_wrapper"
    export BK_BENCHKIT_ROOT="$repo_root"
    # shellcheck source=/dev/null
    source "${repo_root}/scripts/bk_functions.sh"
    bk_capture_build_environment_snapshot
  )
fi

exec "$real_tool" "$@"
