#!/bin/bash
# External inference checkout selection, kept out of ordinary build/run helpers.
bk_perftools_ensure_root() {
  local root="$1" repo="$2" ref="$3" pin="$4" fetch_enabled="$5"
  local commit actual dirty cache_root resolved_ref prefix
  if [[ -n "$pin" && ! "$pin" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo 'ERROR: PerfTools commit must be a full SHA' >&2
    return 1
  fi
  if [[ -n "$root" && -d "$root" ]] && { [[ ! -d "$root/.git" ]] || git -C "$root" rev-parse HEAD >/dev/null 2>&1; }; then
    if [[ -n "$pin" ]]; then
      prefix=$(git -C "$root" rev-parse --show-prefix) || return 1
      if [[ -n "$prefix" ]]; then
        echo "ERROR: PerfTools root must be the checkout root" >&2
        return 1
      fi
      actual=$(git -C "$root" rev-parse HEAD) || return 1
      dirty=$(git -C "$root" status --porcelain --untracked-files=all) || return 1
      if [[ "${actual,,}" != "${pin,,}" || -n "$dirty" ]]; then
        echo 'ERROR: PerfTools checkout does not match the pinned clean commit' >&2
        return 1
      fi
    fi
    printf '%s\n' "$root"
    return 0
  fi
  if [[ "$fetch_enabled" != true ]]; then
    if [[ -n "$pin" ]]; then
      echo 'ERROR: pinned PerfTools checkout is unavailable' >&2
      return 1
    fi
    printf '%s\n' "$root"
    return 0
  fi
  if [[ -n "$pin" ]]; then
    commit="$pin"
  else
    resolved_ref="$ref"
    if [[ "$ref" != refs/* ]]; then resolved_ref="refs/heads/$ref"; fi
    commit=$(set -o pipefail; git ls-remote -- "$repo" "$resolved_ref" "${resolved_ref}^{}" | awk 'NR == 1 {head=$1} /\^\{\}$/ {peeled=$1} END {print peeled ? peeled : head}') || return 1
    if [[ ! "$commit" =~ ^[0-9a-fA-F]{40}$ ]]; then
      echo 'ERROR: PerfTools ref could not be resolved' >&2
      return 1
    fi
  fi
  cache_root="${BK_PERFTOOLS_CACHE_DIR:-.benchkit_estimation_tools/PerfTools}"
  root="${root:-${cache_root}/${commit}}"
  if [[ ! -d "$root/.git" ]]; then
    mkdir -p "$root" || return 1
    git -C "$root" init -q >&2 || return 1
    git -C "$root" remote add origin "$repo" >&2 || return 1
  fi
  if ! git -C "$root" rev-parse HEAD >/dev/null 2>&1; then
    git -C "$root" fetch --depth 1 origin "$commit" >&2 || return 1
    git -C "$root" checkout --detach FETCH_HEAD >&2 || return 1
  fi
  actual=$(git -C "$root" rev-parse HEAD) || return 1
  dirty=$(git -C "$root" status --porcelain --untracked-files=all) || return 1
  if [[ "${actual,,}" != "${commit,,}" || -n "$dirty" ]]; then
    echo 'ERROR: PerfTools cached checkout does not match the resolved clean commit' >&2
    return 1
  fi
  printf '%s\n' "$root"
}
