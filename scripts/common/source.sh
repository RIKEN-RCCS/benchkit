#!/bin/bash
# Shared function definitions; loaded by the appropriate Benchkit entrypoint.

bk_decode_base64_value() {
  if command -v base64 >/dev/null 2>&1; then
    base64 --decode 2>/dev/null || base64 -d 2>/dev/null
    return $?
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl base64 -d -A
    return $?
  fi
  return 1
}

bk_env_file_value() {
  _bk_env_file="$1"
  _bk_env_key="$2"
  _bk_env_line=""

  [ -f "$_bk_env_file" ] || return 0

  _bk_env_line=$(awk -F= -v k="${_bk_env_key}_B64" '$1 == k {print substr($0, length(k) + 2); exit}' "$_bk_env_file")
  if [ -n "$_bk_env_line" ]; then
    printf '%s' "$_bk_env_line" | bk_decode_base64_value 2>/dev/null || true
    return 0
  fi

  _bk_env_line=$(awk -F= -v k="$_bk_env_key" '
    $1 == k {
      print substr($0, length(k) + 2)
      exit
    }
  ' "$_bk_env_file")
  if [ -n "$_bk_env_line" ]; then
    printf '%s' "$_bk_env_line"
    return 0
  fi

  awk -v key="$_bk_env_key" '
    index($0, "export " key "=\"") == 1 && substr($0, length($0), 1) == "\"" {
      prefix = "export " key "=\""
      value = substr($0, length(prefix) + 1, length($0) - length(prefix) - 1)
      if (value !~ /[`$\\]/) {
        print value
      }
      exit
    }
  ' "$_bk_env_file"
}

bk_base64_encode_value() {
  if command -v base64 >/dev/null 2>&1; then
    printf '%s' "$1" | base64 | tr -d '\r\n'
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    printf '%s' "$1" | openssl base64 -A | tr -d '\r\n'
    return 0
  fi
  echo "bk_base64_encode_value: neither base64 nor openssl found" >&2
  return 1
}

bk_md5_file() {
  _bk_hash_file="$1"
  if command -v md5sum >/dev/null 2>&1; then
    md5sum "$_bk_hash_file" | awk '{print $1}'
    return ${PIPESTATUS[0]}
  fi
  if command -v md5 >/dev/null 2>&1; then
    md5 -r "$_bk_hash_file" | awk '{print $1}'
    return ${PIPESTATUS[0]}
  fi
  return 1
}

bk_sha256_file() {
  _bk_hash_file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$_bk_hash_file" | awk '{print $1}'
    return ${PIPESTATUS[0]}
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$_bk_hash_file" | awk '{print $1}'
    return ${PIPESTATUS[0]}
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 -r "$_bk_hash_file" | awk '{print $1}'
    return ${PIPESTATUS[0]}
  fi
  return 1
}

bk_lower_hex() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

bk_validate_hex_length() {
  _bk_hash_value="$1"
  _bk_hash_len="$2"
  _bk_hash_label="$3"
  if [ "${#_bk_hash_value}" -ne "$_bk_hash_len" ]; then
    echo "${_bk_hash_label}: expected ${_bk_hash_len} hex characters, got ${#_bk_hash_value}" >&2
    return 1
  fi
  case "$_bk_hash_value" in
    *[!0-9a-f]*)
      echo "${_bk_hash_label}: expected lowercase hex characters" >&2
      return 1
      ;;
  esac
  return 0
}

bk_verify_file_sha256() {
  _bk_file_path="$1"
  _bk_expected_sha256="$(bk_lower_hex "${2:-}")"
  _bk_label="${3:-source archive}"
  _bk_actual_sha256=""

  if [ -z "$_bk_expected_sha256" ] && [ "${BK_REQUIRE_SOURCE_SHA256:-false}" = "true" ]; then
    echo "${_bk_label}: expected sha256 is required when BK_REQUIRE_SOURCE_SHA256=true" >&2
    return 1
  fi

  if ! _bk_actual_sha256=$(bk_sha256_file "$_bk_file_path"); then
    echo "${_bk_label}: unable to compute sha256 for $_bk_file_path" >&2
    return 1
  fi
  _bk_actual_sha256="$(bk_lower_hex "$_bk_actual_sha256")"

  if [ -n "$_bk_expected_sha256" ]; then
    bk_validate_hex_length "$_bk_expected_sha256" 64 "${_bk_label} sha256" || return 1
    if [ "$_bk_actual_sha256" != "$_bk_expected_sha256" ]; then
      echo "${_bk_label}: sha256 mismatch for $_bk_file_path" >&2
      echo "  expected: $_bk_expected_sha256" >&2
      echo "  actual:   $_bk_actual_sha256" >&2
      return 1
    fi
  fi

  printf '%s\n' "$_bk_actual_sha256"
}

bk_write_source_info_env() {
  _bk_source_type="$1"
  _bk_repo_url="${2:-}"
  _bk_branch="${3:-}"
  _bk_commit_hash="${4:-}"
  _bk_file_path="${5:-}"
  _bk_md5sum="${6:-}"
  _bk_sha256sum="${7:-}"
  _bk_container_path="${8:-${BK_SOURCE_CONTAINER_PATH:-}}"
  _bk_container_sha256sum="${9:-${BK_SOURCE_CONTAINER_SHA256:-}}"
  _bk_ref_name="${10:-}"
  _bk_ref_kind="${11:-}"
  _bk_resolved_commit="${12:-}"

  if ! command -v base64 >/dev/null 2>&1 && ! command -v openssl >/dev/null 2>&1; then
    echo "bk_write_source_info_env: neither base64 nor openssl found" >&2
    return 1
  fi

  {
    printf 'BK_SOURCE_INFO_FORMAT=base64-v1\n'
    printf 'BK_SOURCE_TYPE_B64=%s\n' "$(bk_base64_encode_value "$_bk_source_type")"
    printf 'BK_REPO_URL_B64=%s\n' "$(bk_base64_encode_value "$_bk_repo_url")"
    printf 'BK_BRANCH_B64=%s\n' "$(bk_base64_encode_value "$_bk_branch")"
    printf 'BK_COMMIT_HASH_B64=%s\n' "$(bk_base64_encode_value "$_bk_commit_hash")"
    printf 'BK_FILE_PATH_B64=%s\n' "$(bk_base64_encode_value "$_bk_file_path")"
    printf 'BK_MD5SUM_B64=%s\n' "$(bk_base64_encode_value "$_bk_md5sum")"
    printf 'BK_SHA256SUM_B64=%s\n' "$(bk_base64_encode_value "$_bk_sha256sum")"
    printf 'BK_CONTAINER_IMAGE_PATH_B64=%s\n' "$(bk_base64_encode_value "$_bk_container_path")"
    printf 'BK_CONTAINER_IMAGE_SHA256SUM_B64=%s\n' "$(bk_base64_encode_value "$_bk_container_sha256sum")"
    printf 'BK_SOURCE_REF_NAME_B64=%s\n' "$(bk_base64_encode_value "$_bk_ref_name")"
    printf 'BK_SOURCE_REF_KIND_B64=%s\n' "$(bk_base64_encode_value "$_bk_ref_kind")"
    printf 'BK_SOURCE_RESOLVED_COMMIT_B64=%s\n' "$(bk_base64_encode_value "$_bk_resolved_commit")"
  } > results/source_info.env
}

bk_record_file_source_info() {
  _bk_file_src="$1"
  _bk_expected_sha256="${2:-}"
  _bk_file_label="${3:-source archive}"
  _bk_abs_file_path=""
  _bk_md5sum=""
  _bk_sha256sum=""

  if [ ! -f "$_bk_file_src" ]; then
    echo "${_bk_file_label}: file not found: $_bk_file_src" >&2
    return 1
  fi

  case "$_bk_file_src" in
    /*) _bk_abs_file_path="$_bk_file_src" ;;
    *) _bk_abs_file_path="$(pwd)/$_bk_file_src" ;;
  esac

  if ! _bk_sha256sum=$(bk_verify_file_sha256 "$_bk_file_src" "$_bk_expected_sha256" "$_bk_file_label"); then
    return 1
  fi

  if _bk_md5sum=$(bk_md5_file "$_bk_file_src"); then
    _bk_md5sum="$(bk_lower_hex "$_bk_md5sum")"
  else
    echo "${_bk_file_label}: warning: neither md5sum nor md5 found" >&2
    _bk_md5sum=""
  fi

  BK_SOURCE_TYPE="file"
  BK_FILE_PATH="$_bk_abs_file_path"
  BK_MD5SUM="$_bk_md5sum"
  BK_SHA256SUM="$_bk_sha256sum"
  export BK_SOURCE_TYPE BK_FILE_PATH BK_MD5SUM BK_SHA256SUM

  mkdir -p results
  bk_write_source_info_env "file" "" "" "" "$BK_FILE_PATH" "$BK_MD5SUM" "$BK_SHA256SUM"
}

bk_git_ref_kind() {
  _bk_git_dir="$1"
  _bk_ref_name="${2:-}"

  case "$_bk_ref_name" in
    ""|HEAD|detached)
      printf '%s\n' "commit"
      return 0
      ;;
  esac

  if git -C "$_bk_git_dir" show-ref --verify --quiet "refs/heads/${_bk_ref_name}"; then
    printf '%s\n' "branch"
    return 0
  fi
  if git -C "$_bk_git_dir" show-ref --verify --quiet "refs/remotes/origin/${_bk_ref_name}"; then
    printf '%s\n' "branch"
    return 0
  fi
  if git -C "$_bk_git_dir" show-ref --verify --quiet "refs/tags/${_bk_ref_name}"; then
    printf '%s\n' "tag"
    return 0
  fi
  if git -C "$_bk_git_dir" rev-parse --verify --quiet "${_bk_ref_name}^{commit}" >/dev/null 2>&1; then
    printf '%s\n' "commit"
    return 0
  fi

  printf '%s\n' "unknown"
}

# bk_fetch_source - Fetch source code and collect metadata.
#
# Usage:
#   bk_fetch_source <source> <dest_dir> [branch_or_tag] [expected_commit_or_sha256]
#
# Arguments:
#   $1 - source: Repository URL or archive file path
#   $2 - dest_dir: Destination directory name
#   $3 - branch_or_tag: (optional) Git branch or tag to clone
#   $4 - expected commit for git, expected sha256 for archive (optional)
#
# Auto-detection:
#   http:// / https:// prefix or .git suffix → git clone
#   Otherwise → tar archive extraction
#
# Environment variables set:
#   BK_SOURCE_TYPE  - "git" or "file"
#   BK_REPO_URL     - (git) Repository URL
#   BK_BRANCH       - (git) Source ref display name
#   BK_COMMIT_HASH  - (git) Full 40-char commit hash
#   BK_SOURCE_REF_NAME         - (git) Source ref name used for provenance/cache checks
#   BK_SOURCE_REF_KIND         - (git) branch, tag, commit, or unknown
#   BK_SOURCE_RESOLVED_COMMIT  - (git) Full 40-char commit resolved from the source ref
#   BK_FILE_PATH    - (file) Absolute path to archive
#   BK_MD5SUM       - (file) Full 32-char md5sum
#   BK_SHA256SUM    - (file) Full 64-char sha256sum
#
# Side effects:
#   Writes results/source_info.env as data, not executable shell
#
# Returns:
#   0 - success
#   1 - failure (error message on stderr)
bk_fetch_source() {
  if [ $# -lt 2 ]; then
    echo "bk_fetch_source: requires <source> and <dest_dir> arguments" >&2
    return 1
  fi

  _bk_src="$1"
  _bk_dest="$2"
  _bk_branch="${3:-}"
  _bk_expected="${4:-}"

  # Auto-detect source type
  _bk_is_git=0
  case "$_bk_src" in
    http://*|https://*)
      _bk_is_git=1
      ;;
    *.git)
      _bk_is_git=1
      ;;
  esac

  mkdir -p results

  if [ "$_bk_is_git" -eq 1 ]; then
    # --- Git clone path ---
    BK_SOURCE_TYPE="git"
    BK_REPO_URL="$_bk_src"
    export BK_SOURCE_TYPE BK_REPO_URL
    _bk_expected_commit="$(bk_lower_hex "${BK_FETCH_EXPECTED_COMMIT:-$_bk_expected}")"
    if [ -n "$_bk_expected_commit" ]; then
      bk_validate_hex_length "$_bk_expected_commit" 40 "bk_fetch_source expected commit" || return 1
    fi

    if [ -d "$_bk_dest" ]; then
      # Directory exists: skip clone, collect metadata from existing dir
      BK_BRANCH=$(git -C "$_bk_dest" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
      BK_COMMIT_HASH=$(git -C "$_bk_dest" rev-parse HEAD 2>/dev/null || echo "")
    else
      # Perform git clone
      if [ -n "$_bk_branch" ]; then
        if ! git clone --branch "$_bk_branch" "$_bk_src" "$_bk_dest" 2>&1; then
          echo "bk_fetch_source: git clone failed for '$_bk_src' (branch: $_bk_branch)" >&2
          return 1
        fi
        BK_BRANCH="$_bk_branch"
      else
        if ! git clone "$_bk_src" "$_bk_dest" 2>&1; then
          echo "bk_fetch_source: git clone failed for '$_bk_src'" >&2
          return 1
        fi
        BK_BRANCH=$(git -C "$_bk_dest" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
      fi
      BK_COMMIT_HASH=$(git -C "$_bk_dest" rev-parse HEAD 2>/dev/null || echo "")
    fi

    if [ -n "$_bk_expected_commit" ]; then
      if [ "$BK_COMMIT_HASH" != "$_bk_expected_commit" ]; then
        if ! git -C "$_bk_dest" cat-file -e "${_bk_expected_commit}^{commit}" 2>/dev/null; then
          git -C "$_bk_dest" fetch origin "$_bk_expected_commit" 2>/dev/null || true
        fi
        if ! git -C "$_bk_dest" checkout --detach "$_bk_expected_commit" 2>&1; then
          echo "bk_fetch_source: expected commit not available: $_bk_expected_commit" >&2
          return 1
        fi
        BK_COMMIT_HASH=$(git -C "$_bk_dest" rev-parse HEAD 2>/dev/null || echo "")
      fi
      if [ "$BK_COMMIT_HASH" != "$_bk_expected_commit" ]; then
        echo "bk_fetch_source: commit mismatch for '$_bk_src'" >&2
        echo "  expected: $_bk_expected_commit" >&2
        echo "  actual:   $BK_COMMIT_HASH" >&2
        return 1
      fi
      if [ -z "$BK_BRANCH" ] || [ "$BK_BRANCH" = "HEAD" ]; then
        BK_BRANCH="${_bk_branch:-detached}"
      fi
    fi

    BK_SOURCE_REF_NAME="${BK_BRANCH:-}"
    BK_SOURCE_REF_KIND=$(bk_git_ref_kind "$_bk_dest" "$BK_SOURCE_REF_NAME")
    BK_SOURCE_RESOLVED_COMMIT="$BK_COMMIT_HASH"
    export BK_BRANCH BK_COMMIT_HASH BK_SOURCE_REF_NAME BK_SOURCE_REF_KIND BK_SOURCE_RESOLVED_COMMIT

    bk_write_source_info_env \
      "git" "$BK_REPO_URL" "$BK_BRANCH" "$BK_COMMIT_HASH" "" "" "" "" "" \
      "$BK_SOURCE_REF_NAME" "$BK_SOURCE_REF_KIND" "$BK_SOURCE_RESOLVED_COMMIT"

  else
    # --- File archive path ---
    _bk_expected_sha256="${BK_FETCH_EXPECTED_SHA256:-$_bk_expected}"

    # Check archive exists
    if [ ! -f "$_bk_src" ]; then
      echo "bk_fetch_source: archive file not found: '$_bk_src'" >&2
      return 1
    fi

    bk_record_file_source_info "$_bk_src" "$_bk_expected_sha256" "bk_fetch_source archive" || return 1

    # Extract archive if dest_dir doesn't exist
    if [ ! -d "$_bk_dest" ]; then
      if ! tar -xzf "$_bk_src" -C "$(dirname "$_bk_dest")" 2>&1; then
        echo "bk_fetch_source: tar extraction failed for '$_bk_src'" >&2
        return 1
      fi
    fi

  fi

  return 0
}

bk_fetch_recorded_source() {
  if [ $# -lt 2 ]; then
    echo "bk_fetch_recorded_source: requires <source> and <dest_dir> arguments" >&2
    return 1
  fi

  _bk_recorded_src="$1"
  _bk_recorded_dest="$2"
  _bk_recorded_ref="${3:-}"
  _bk_recorded_expected="${4:-}"
  _bk_recorded_info_file="${5:-results/source_info.env}"

  if [ -f "$_bk_recorded_info_file" ]; then
    _bk_recorded_type=$(bk_env_file_value "$_bk_recorded_info_file" BK_SOURCE_TYPE)
    if [ "$_bk_recorded_type" = "git" ]; then
      _bk_recorded_repo_url=$(bk_env_file_value "$_bk_recorded_info_file" BK_REPO_URL)
      _bk_recorded_source_ref=$(bk_env_file_value "$_bk_recorded_info_file" BK_SOURCE_REF_NAME)
      if [ -z "$_bk_recorded_source_ref" ]; then
        _bk_recorded_source_ref=$(bk_env_file_value "$_bk_recorded_info_file" BK_BRANCH)
      fi
      _bk_recorded_commit=$(bk_env_file_value "$_bk_recorded_info_file" BK_SOURCE_RESOLVED_COMMIT)
      if [ -z "$_bk_recorded_commit" ]; then
        _bk_recorded_commit=$(bk_env_file_value "$_bk_recorded_info_file" BK_COMMIT_HASH)
      fi

      if [ -n "$_bk_recorded_repo_url" ]; then
        _bk_recorded_src="$_bk_recorded_repo_url"
      fi
      if [ -n "$_bk_recorded_source_ref" ]; then
        _bk_recorded_ref="$_bk_recorded_source_ref"
      fi
      if [ -n "$_bk_recorded_commit" ]; then
        _bk_recorded_expected="$_bk_recorded_commit"
      fi
    fi
  fi

  bk_fetch_source "$_bk_recorded_src" "$_bk_recorded_dest" "$_bk_recorded_ref" "$_bk_recorded_expected"
}

# Opt-in build/runtime handoff; legacy source acquisition remains unchanged.
source "${BASH_SOURCE[0]%/*}/source_bundle.sh"
