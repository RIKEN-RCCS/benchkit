#!/bin/bash
# Validate routes with the same shell/jq runtime as matrix generation.
set -euo pipefail
export LC_ALL=C

fail() {
    echo "Execution route configuration could not be read or validated" >&2
    exit 1
}

system_file=config/system.csv
selected=
check=false
while (($#)); do
    case "$1" in
        --check) check=true; shift ;;
        --system-file|--selected-system)
            (($# >= 2)) || fail
            if [[ "$1" == --system-file ]]; then system_file=$2; else selected=$2; fi
            shift 2 ;;
        *) fail ;;
    esac
done

source_kind="file"
if [[ -v BK_EXECUTION_ROUTE_SNAPSHOT ]]; then
    [[ -z "${BK_EXECUTION_ROUTES_FILE:-}" ]] || fail
    source_kind=snapshot
    raw=$BK_EXECUTION_ROUTE_SNAPSHOT
else
    [[ -f "${BK_EXECUTION_ROUTES_FILE:-}" && -r "$BK_EXECUTION_ROUTES_FILE" ]] || fail
    # Stop at NUL or the size limit; neither may be silently truncated.
    if IFS= read -r -d '' -n 1048577 raw < "$BK_EXECUTION_ROUTES_FILE"; then fail; fi
fi
[[ ${#raw} -le 1048576 && -r "$system_file" ]] || fail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! resolved=$(printf '%s' "$raw" | jq -nce --stream \
    --rawfile systems_csv "$system_file" --arg systems_json '' \
    --arg source "$source_kind" --arg selected "$selected" \
    -f "$script_dir/execution_routes.jq" 2>/dev/null); then fail; fi
if ! resolved=$(jq -ce '.resolved // error("invalid")' 2>/dev/null <<< "$resolved"); then fail; fi
if "$check"; then
    echo "Execution route configuration is valid"
else
    printf '%s\n' "$resolved"
fi
