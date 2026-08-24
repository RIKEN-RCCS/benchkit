#!/bin/bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <code> <system> <program_path>" >&2
  exit 2
fi

code="$1"
system="$2"
program_path="$3"

repo_root="${BK_BENCHKIT_ROOT:-$(pwd)}"
cache_project_slug="${CUSTOM_RUNNER_PROJECT_SLUG:-${CI_PROJECT_PATH_SLUG:-unknown}}"
case "$cache_project_slug" in
  ""|.|..|*/*|*../*|*..*) cache_project_slug="unknown" ;;
esac
if [ -n "${BK_BUILD_CACHE_DIR:-}" ]; then
  cache_root="$BK_BUILD_CACHE_DIR"
elif [ -n "${CUSTOM_DIR:-}" ]; then
  cache_root="${CUSTOM_DIR%/}/build_cache/${cache_project_slug}"
else
  cache_root=""
fi
cache_dir=""
cache_manifest=""
if [ -n "$cache_root" ]; then
  cache_dir="${cache_root}/${code}/${system}"
  cache_manifest="${cache_dir}/manifest.env"
fi
status_file="${repo_root}/results/build_cache.env"

source "${repo_root}/scripts/bk_functions.sh"

validate_path_component() {
  local value="$1"
  local label="$2"

  case "$value" in
    ""|.|..|*/*|*../*|*..*)
      echo "build cache: invalid ${label}: ${value}" >&2
      return 1
      ;;
  esac
}

decode_base64_value() {
  if base64 --decode >/dev/null 2>&1 </dev/null; then
    base64 --decode
    return 0
  fi
  if base64 -d >/dev/null 2>&1 </dev/null; then
    base64 -d
    return 0
  fi
  if base64 -D >/dev/null 2>&1 </dev/null; then
    base64 -D
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl base64 -d -A
    return 0
  fi
  return 1
}

env_file_value() {
  local file="$1"
  local key="$2"
  local line=""

  line=$(awk -F= -v k="${key}_B64" '$1 == k {print substr($0, length(k) + 2); exit}' "$file")
  if [ -n "$line" ]; then
    printf '%s' "$line" | decode_base64_value 2>/dev/null || true
    return 0
  fi

  awk -F= -v k="$key" '
    $1 == k {
      value = substr($0, length(k) + 2)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      gsub(/^"|"$/, "", value)
      print value
      exit
    }
  ' "$file"
}

manifest_value() {
  local key="$1"

  awk -F= -v k="$key" '$1 == k {print substr($0, length(k) + 2); exit}' "$cache_manifest"
}

cache_dir_available() {
  if [ -z "$cache_root" ]; then
    return 1
  fi
  case "$cache_root" in
    /*) return 0 ;;
    *) return 1 ;;
  esac
}

cache_dir_unavailable_reason() {
  if [ -z "$cache_root" ]; then
    printf '%s\n' "BK_BUILD_CACHE_DIR is not set and CUSTOM_DIR is unavailable"
    return 0
  fi
  case "$cache_root" in
    /*) printf '%s\n' "" ;;
    *) printf '%s\n' "BK_BUILD_CACHE_DIR must be an absolute persistent path" ;;
  esac
}

write_status() {
  local status="$1"
  local reason="${2:-}"
  local stored="${3:-false}"

  mkdir -p "${repo_root}/results"
  {
    printf 'BK_BUILD_CACHE_STATUS=%s\n' "$status"
    printf 'BK_BUILD_CACHE_REASON_B64=%s\n' "$(bk_base64_encode_value "$reason")"
    printf 'BK_BUILD_CACHE_DIR_B64=%s\n' "$(bk_base64_encode_value "$cache_dir")"
    printf 'BK_BUILD_CACHE_STORED=%s\n' "$stored"
  } > "$status_file"
}

build_inputs_hash() {
  local file_list
  local hash_list
  local file

  file_list=$(mktemp)
  hash_list=$(mktemp)
  if git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$repo_root" ls-files \
      "programs/${code}" \
      "scripts/bk_functions.sh" \
      "scripts/build_tool_wrappers" \
      "scripts/build_with_cache.sh" \
      "scripts/collect_environment_snapshot.sh" \
      "scripts/matrix_generate.sh" \
      > "$file_list"
  else
    find "${repo_root}/programs/${code}" "${repo_root}/scripts/build_tool_wrappers" \
      -type f -print > "$file_list" 2>/dev/null || true
    printf '%s\n' \
      "scripts/bk_functions.sh" \
      "scripts/build_with_cache.sh" \
      "scripts/collect_environment_snapshot.sh" \
      "scripts/matrix_generate.sh" \
      >> "$file_list"
  fi

  for file in ${BK_BUILD_CACHE_EXTRA_INPUTS:-}; do
    printf '%s\n' "$file" >> "$file_list"
  done

  LC_ALL=C sort -u "$file_list" | while IFS= read -r file; do
    label="$file"
    [ -n "$file" ] || continue
    case "$file" in
      /*)
        case "$file" in
          "${repo_root}/"*) label="${file#"${repo_root}/"}" ;;
        esac
        ;;
      *) file="${repo_root}/${file}" ;;
    esac
    if [ -f "$file" ]; then
      printf '%s  %s\n' "$(bk_sha256_file "$file")" "$label" >> "$hash_list"
    fi
  done

  bk_sha256_file "$hash_list"
  rm -f "$file_list" "$hash_list"
}

resolve_git_branch_commit() {
  local repo_url="$1"
  local branch="$2"
  local commit=""

  if [ -z "$repo_url" ] || [ -z "$branch" ] || [ "$branch" = "HEAD" ] || [ "$branch" = "detached" ]; then
    return 1
  fi

  commit=$(git ls-remote "$repo_url" "refs/heads/${branch}" 2>/dev/null | awk 'NR == 1 {print $1}')
  if [ -z "$commit" ]; then
    commit=$(git ls-remote "$repo_url" "$branch" 2>/dev/null | awk 'NR == 1 {print $1}')
  fi
  [ -n "$commit" ] || return 1
  printf '%s\n' "$commit"
}

validate_cached_source() {
  local source_info_file="$1"
  local source_type
  local repo_url
  local branch
  local cached_commit
  local current_commit
  local file_path
  local cached_sha256
  local current_sha256
  local container_path
  local cached_container_sha256
  local current_container_sha256

  source_type=$(env_file_value "$source_info_file" BK_SOURCE_TYPE)
  case "$source_type" in
    git)
      repo_url=$(env_file_value "$source_info_file" BK_REPO_URL)
      branch=$(env_file_value "$source_info_file" BK_BRANCH)
      cached_commit=$(env_file_value "$source_info_file" BK_COMMIT_HASH)
      if ! current_commit=$(resolve_git_branch_commit "$repo_url" "$branch"); then
        echo "cannot verify current git ref for ${repo_url} ${branch}"
        return 1
      fi
      if [ "$current_commit" != "$cached_commit" ]; then
        echo "source commit changed: cached ${cached_commit}, current ${current_commit}"
        return 1
      fi
      ;;
    file)
      file_path=$(env_file_value "$source_info_file" BK_FILE_PATH)
      cached_sha256=$(env_file_value "$source_info_file" BK_SHA256SUM)
      if [ -z "$file_path" ] || [ -z "$cached_sha256" ] || [ ! -f "$file_path" ]; then
        echo "cannot verify cached source archive"
        return 1
      fi
      current_sha256=$(bk_sha256_file "$file_path")
      if [ "$current_sha256" != "$cached_sha256" ]; then
        echo "source archive sha256 changed"
        return 1
      fi
      ;;
    *)
      echo "unsupported cached source type: ${source_type:-empty}"
      return 1
      ;;
  esac

  container_path=$(env_file_value "$source_info_file" BK_CONTAINER_IMAGE_PATH)
  cached_container_sha256=$(env_file_value "$source_info_file" BK_CONTAINER_IMAGE_SHA256SUM)
  if [ -n "$cached_container_sha256" ]; then
    if [ -z "$container_path" ] || [ ! -f "$container_path" ]; then
      echo "cannot verify cached container image"
      return 1
    fi
    current_container_sha256=$(bk_sha256_file "$container_path")
    if [ "$current_container_sha256" != "$cached_container_sha256" ]; then
      echo "container image sha256 changed"
      return 1
    fi
    return 0
  fi

  if [ "${BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE:-false}" != "true" ]; then
    echo "host build cache restore requires BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE=true"
    return 1
  fi
  if [ -z "${BK_BUILD_CACHE_ENV_KEY:-}" ]; then
    echo "host build cache restore requires non-empty BK_BUILD_CACHE_ENV_KEY"
    return 1
  fi
  if [ "$(manifest_value BK_CACHE_ENV_KEY_B64 | decode_base64_value 2>/dev/null || true)" != "$BK_BUILD_CACHE_ENV_KEY" ]; then
    echo "host build cache environment key changed"
    return 1
  fi
}

restore_cache() {
  local current_inputs_hash
  local cached_inputs_hash
  local cached_source_info="${cache_dir}/results/source_info.env"
  local reason

  if [ "${BK_BUILD_CACHE_ENABLED:-true}" != "true" ]; then
    write_status disabled "BK_BUILD_CACHE_ENABLED is not true"
    return 1
  fi
  if ! cache_dir_available; then
    write_status disabled "$(cache_dir_unavailable_reason)"
    return 1
  fi
  if [ ! -f "$cache_manifest" ]; then
    write_status miss "cache manifest is missing"
    return 1
  fi
  if [ ! -d "${cache_dir}/artifacts" ] || [ ! -f "$cached_source_info" ]; then
    write_status miss "cached artifacts or source_info.env are missing"
    return 1
  fi

  current_inputs_hash=$(build_inputs_hash)
  cached_inputs_hash=$(manifest_value BK_CACHE_BUILD_INPUTS_SHA256)
  if [ "$current_inputs_hash" != "$cached_inputs_hash" ]; then
    write_status miss "build inputs changed"
    return 1
  fi

  if ! reason=$(validate_cached_source "$cached_source_info"); then
    write_status miss "$reason"
    return 1
  fi

  rm -rf "${repo_root}/artifacts"
  mkdir -p "${repo_root}/artifacts" "${repo_root}/results"
  cp -a "${cache_dir}/artifacts/." "${repo_root}/artifacts/"
  if [ -d "${cache_dir}/results" ]; then
    cp -a "${cache_dir}/results/." "${repo_root}/results/"
  fi
  write_status hit "restored cached build artifacts"
  echo "build cache: hit for ${code}/${system}"
}

store_cache() {
  local tmp_dir
  local inputs_hash
  local source_info_sha256=""
  local source_info_file="${repo_root}/results/source_info.env"
  local container_sha256=""

  if [ "${BK_BUILD_CACHE_ENABLED:-true}" != "true" ]; then
    write_status disabled "BK_BUILD_CACHE_ENABLED is not true"
    return 0
  fi
  if ! cache_dir_available; then
    write_status disabled "$(cache_dir_unavailable_reason)"
    return 0
  fi
  if [ ! -d "${repo_root}/artifacts" ] || [ ! -f "$source_info_file" ]; then
    write_status miss "build completed but artifacts or source_info.env are missing"
    return 0
  fi
  container_sha256=$(env_file_value "$source_info_file" BK_CONTAINER_IMAGE_SHA256SUM)
  if [ -z "$container_sha256" ] && [ -z "${BK_BUILD_CACHE_ENV_KEY:-}" ]; then
    write_status miss "host build cache store requires non-empty BK_BUILD_CACHE_ENV_KEY"
    return 0
  fi

  inputs_hash=$(build_inputs_hash)
  source_info_sha256=$(bk_sha256_file "$source_info_file")
  tmp_dir="${cache_dir}.tmp.$$"
  rm -rf "$tmp_dir"
  mkdir -p "${tmp_dir}/artifacts" "${tmp_dir}/results"
  cp -a "${repo_root}/artifacts/." "${tmp_dir}/artifacts/"
  cp "$source_info_file" "${tmp_dir}/results/source_info.env"
  if [ -f "${repo_root}/results/environment_snapshot_build_actual.json" ]; then
    cp "${repo_root}/results/environment_snapshot_build_actual.json" \
      "${tmp_dir}/results/environment_snapshot_build_actual.json"
  fi
  {
    printf 'BK_BUILD_CACHE_FORMAT=base64-v1\n'
    printf 'BK_CACHE_CODE_B64=%s\n' "$(bk_base64_encode_value "$code")"
    printf 'BK_CACHE_SYSTEM_B64=%s\n' "$(bk_base64_encode_value "$system")"
    printf 'BK_CACHE_BUILD_INPUTS_SHA256=%s\n' "$inputs_hash"
    printf 'BK_CACHE_SOURCE_INFO_SHA256=%s\n' "$source_info_sha256"
    printf 'BK_CACHE_ENV_KEY_B64=%s\n' "$(bk_base64_encode_value "${BK_BUILD_CACHE_ENV_KEY:-}")"
    printf 'BK_CACHE_CREATED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "${tmp_dir}/manifest.env"

  rm -rf "$cache_dir"
  mkdir -p "$(dirname "$cache_dir")"
  mv "$tmp_dir" "$cache_dir"
  write_status miss "stored cache after build" true
  echo "build cache: stored ${code}/${system}"
}

validate_path_component "$code" code
validate_path_component "$system" system

case "$program_path" in
  /*) ;;
  *) program_path="${repo_root}/${program_path}" ;;
esac
if [ ! -f "${program_path}/build.sh" ]; then
  echo "build cache: build script not found: ${program_path}/build.sh" >&2
  exit 2
fi

mkdir -p "${repo_root}/results"
export BK_SYSTEM="${BK_SYSTEM:-$system}"
export BK_BENCHKIT_ROOT="$repo_root"
export PATH="${repo_root}/scripts/build_tool_wrappers:${PATH:-}"

if restore_cache; then
  exit 0
fi

echo "build cache: miss for ${code}/${system}; running build.sh"
bash "${program_path}/build.sh" "$system"
store_cache
