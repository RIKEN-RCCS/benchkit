#!/bin/bash
# External inference checkout selection, kept out of ordinary build/run helpers.
bk_perftools_ensure_root() {
  local repo="$1" ref="$2" pin="$3" root
  local commit actual dirty cache_root resolved_ref prefix
  if [[ -n "$pin" && ! "$pin" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo 'ERROR: PerfTools commit must be a full SHA' >&2
    return 1
  fi
  if [[ -n "$pin" ]]; then
    commit="${pin,,}"
  else
    resolved_ref="$ref"
    if [[ "$ref" != refs/* ]]; then resolved_ref="refs/heads/$ref"; fi
    commit=$(set -o pipefail; git ls-remote -- "$repo" "$resolved_ref" "${resolved_ref}^{}" 2>/dev/null | awk 'NR == 1 {head=$1} /\^\{\}$/ {peeled=$1} END {print peeled ? peeled : head}') || {
      echo 'ERROR: PerfTools ref lookup failed' >&2
      return 1
    }
    if [[ ! "$commit" =~ ^[0-9a-fA-F]{40}$ ]]; then
      echo 'ERROR: PerfTools ref could not be resolved' >&2
      return 1
    fi
  fi
  cache_root="${BK_PERFTOOLS_CACHE_DIR:-.benchkit_estimation_tools/PerfTools}"
  root="${cache_root}/${commit}"
  if [[ -L "$root" || -L "$root/.git" ]]; then
    echo 'ERROR: PerfTools cached checkout must not be a symlink' >&2
    return 1
  fi
  if [[ ! -d "$root/.git" ]]; then
    if [[ -e "$root" ]]; then
      echo 'ERROR: PerfTools cache entry is not a checkout' >&2
      return 1
    fi
    mkdir -p "$root" || return 1
    git -C "$root" init -q >&2 || return 1
    git -C "$root" remote add origin "$repo" >&2 || return 1
  fi
  if ! git -C "$root" rev-parse HEAD >/dev/null 2>&1; then
    git -C "$root" fetch --depth 1 origin "$commit" >/dev/null 2>&1 || {
      echo 'ERROR: PerfTools commit fetch failed' >&2
      return 1
    }
    git -C "$root" checkout --detach FETCH_HEAD >/dev/null 2>&1 || {
      echo 'ERROR: PerfTools commit checkout failed' >&2
      return 1
    }
  fi
  prefix=$(git -C "$root" rev-parse --show-prefix) || return 1
  [[ -z "$prefix" ]] || return 1
  actual=$(git -C "$root" rev-parse HEAD) || return 1
  dirty=$(GIT_OPTIONAL_LOCKS=0 git -C "$root" status --porcelain --untracked-files=all) || return 1
  if [[ "${actual,,}" != "${commit,,}" || -n "$dirty" ]]; then
    echo 'ERROR: PerfTools cached checkout does not match the resolved clean commit' >&2
    return 1
  fi
  printf '%s\n' "$root"
}
