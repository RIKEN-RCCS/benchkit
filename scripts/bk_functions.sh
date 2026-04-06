#!/bin/sh
# bk_functions.sh - Common functions for standardized benchmark result output.
# Source this file from Run_Scripts: source scripts/bk_functions.sh
#
# POSIX compatible (no jq dependency).

# bk_emit_result - Output a standardized FOM result line.
#
# Named arguments:
#   --fom <value>          (required, numeric)
#   --fom-version <value>  (optional)
#   --exp <value>          (optional)
#   --nodes <value>        (optional)
#   --numproc-node <value> (optional)
#   --nthreads <value>     (optional)
#   --confidential <value> (optional)
#
# Unknown arguments are silently ignored for future extensibility.
#
# Output format (omitted optional args produce no key:value pair):
#   FOM:<value> [FOM_version:<version>] [Exp:<experiment>] [node_count:<nodes>]
#   [numproc_node:<numproc_node>] [nthreads:<nthreads>] [confidential:<value>]
#
# Exit codes:
#   0 - success
#   1 - missing or invalid --fom
bk_emit_result() {
  _bk_fom=""
  _bk_fom_version=""
  _bk_exp=""
  _bk_nodes=""
  _bk_numproc_node=""
  _bk_nthreads=""
  _bk_confidential=""
  _bk_fom_set=0

  while [ $# -gt 0 ]; do
    case "$1" in
      --fom)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_emit_result: --fom requires a value" >&2
          return 1
        fi
        _bk_fom="$1"
        _bk_fom_set=1
        ;;
      --fom-version)
        shift
        if [ $# -gt 0 ]; then
          _bk_fom_version="$1"
        fi
        ;;
      --exp)
        shift
        if [ $# -gt 0 ]; then
          _bk_exp="$1"
        fi
        ;;
      --nodes)
        shift
        if [ $# -gt 0 ]; then
          _bk_nodes="$1"
        fi
        ;;
      --numproc-node)
        shift
        if [ $# -gt 0 ]; then
          _bk_numproc_node="$1"
        fi
        ;;
      --nthreads)
        shift
        if [ $# -gt 0 ]; then
          _bk_nthreads="$1"
        fi
        ;;
      --confidential)
        shift
        if [ $# -gt 0 ]; then
          _bk_confidential="$1"
        fi
        ;;
      --*)
        # Unknown named argument: skip its value if present
        shift
        if [ $# -gt 0 ]; then
          case "$1" in
            --*) continue ;;  # Next arg is another flag, don't consume it
            *) ;;             # Consume the value
          esac
        fi
        ;;
      *)
        # Ignore positional arguments
        ;;
    esac
    shift
  done

  # Validate --fom is provided
  if [ "$_bk_fom_set" -eq 0 ]; then
    echo "bk_emit_result: --fom is required" >&2
    return 1
  fi

  # Validate --fom is numeric (integer or decimal, with optional leading minus)
  case "$_bk_fom" in
    *[!0-9.eE+-]*)
      echo "bk_emit_result: --fom value must be numeric, got '$_bk_fom'" >&2
      return 1
      ;;
    "")
      echo "bk_emit_result: --fom value must be numeric, got ''" >&2
      return 1
      ;;
  esac
  # Additional check: must contain at least one digit
  case "$_bk_fom" in
    *[0-9]*)
      ;;
    *)
      echo "bk_emit_result: --fom value must be numeric, got '$_bk_fom'" >&2
      return 1
      ;;
  esac

  # Normalize scientific notation (e.g. 3.64E+01 -> 36.415) to plain decimal
  # result.sh parses with grep -Eo 'FOM:[ ]*[0-9.]*' which doesn't match E notation
  case "$_bk_fom" in
    *[eE]*)
      _bk_fom=$(awk "BEGIN {printf \"%.17g\", $_bk_fom}")
      ;;
  esac

  # Build output line
  _bk_output="FOM:${_bk_fom}"

  if [ -n "$_bk_fom_version" ]; then
    _bk_output="${_bk_output} FOM_version:${_bk_fom_version}"
  fi

  if [ -n "$_bk_exp" ]; then
    _bk_output="${_bk_output} Exp:${_bk_exp}"
  fi

  if [ -n "$_bk_nodes" ]; then
    _bk_output="${_bk_output} node_count:${_bk_nodes}"
  fi

  if [ -n "$_bk_numproc_node" ]; then
    _bk_output="${_bk_output} numproc_node:${_bk_numproc_node}"
  fi

  if [ -n "$_bk_nthreads" ]; then
    _bk_output="${_bk_output} nthreads:${_bk_nthreads}"
  fi

  if [ -n "$_bk_confidential" ]; then
    _bk_output="${_bk_output} confidential:${_bk_confidential}"
  fi

  echo "$_bk_output"
  return 0
}

# bk_emit_section - Output a standardized SECTION timing line.
#
# Positional arguments:
#   $1 - section name (required)
#   $2 - time value (required, numeric)
#   $3 - estimation package name (optional)
#   $4 - auxiliary artifact path (optional)
#
# Optional named arguments:
#   --type <value>         (optional, default: regular)
#   --members <value>      (optional, comma-separated related sections for overlap-like entries)
#
# Output format:
#   SECTION:<name> time:<time> [type:<type>] [members:<members>]
#   [estimation_package:<package>] [artifact:<path>]
#
# Exit codes:
#   0 - success
#   1 - missing argument or invalid time value
bk_emit_section() {
  if [ $# -lt 1 ] || [ -z "$1" ]; then
    echo "bk_emit_section: section name is required" >&2
    return 1
  fi

  if [ $# -lt 2 ] || [ -z "$2" ]; then
    echo "bk_emit_section: time value is required" >&2
    return 1
  fi

  _bk_sec_name="$1"
  _bk_sec_time="$2"
  _bk_sec_package="${3:-}"
  _bk_sec_artifact="${4:-}"
  _bk_sec_type="regular"
  _bk_sec_members=""

  shift 4 2>/dev/null || shift $#
  while [ $# -gt 0 ]; do
    case "$1" in
      --type)
        shift
        if [ $# -gt 0 ]; then
          _bk_sec_type="$1"
        fi
        ;;
      --members)
        shift
        if [ $# -gt 0 ]; then
          _bk_sec_members="$1"
        fi
        ;;
    esac
    shift
  done

  # Validate time is numeric (integer or decimal, with optional leading minus)
  case "$_bk_sec_time" in
    *[!0-9.eE+-]*)
      echo "bk_emit_section: time value must be numeric, got '$_bk_sec_time'" >&2
      return 1
      ;;
    "")
      echo "bk_emit_section: time value must be numeric, got ''" >&2
      return 1
      ;;
  esac
  # Must contain at least one digit
  case "$_bk_sec_time" in
    *[0-9]*)
      ;;
    *)
      echo "bk_emit_section: time value must be numeric, got '$_bk_sec_time'" >&2
      return 1
      ;;
  esac

  _bk_sec_output="SECTION:${_bk_sec_name} time:${_bk_sec_time}"

  if [ -n "$_bk_sec_type" ] && [ "$_bk_sec_type" != "regular" ]; then
    _bk_sec_output="${_bk_sec_output} type:${_bk_sec_type}"
  fi

  if [ -n "$_bk_sec_members" ]; then
    _bk_sec_output="${_bk_sec_output} members:${_bk_sec_members}"
  fi

  if [ -n "$_bk_sec_package" ]; then
    _bk_sec_output="${_bk_sec_output} estimation_package:${_bk_sec_package}"
  fi

  if [ -n "$_bk_sec_artifact" ]; then
    _bk_sec_output="${_bk_sec_output} artifact:${_bk_sec_artifact}"
  fi

  echo "$_bk_sec_output"
  return 0
}

# bk_emit_overlap - Backward-compatible wrapper for overlap-like section timing.
#
# Positional arguments:
#   $1 - comma-separated section names (required)
#   $2 - time value (required, numeric)
#   $3 - estimation package name (optional)
#   $4 - auxiliary artifact path (optional)
#
# Exit codes:
#   0 - success
#   1 - missing argument or invalid time value
bk_emit_overlap() {
  if [ $# -lt 1 ] || [ -z "$1" ]; then
    echo "bk_emit_overlap: section names are required" >&2
    return 1
  fi

  if [ $# -lt 2 ] || [ -z "$2" ]; then
    echo "bk_emit_overlap: time value is required" >&2
    return 1
  fi

  _bk_ovl_sections="$1"
  _bk_ovl_time="$2"
  _bk_ovl_package="${3:-}"
  _bk_ovl_artifact="${4:-}"

  # Validate time is numeric (integer or decimal, with optional leading minus)
  case "$_bk_ovl_time" in
    *[!0-9.eE+-]*)
      echo "bk_emit_overlap: time value must be numeric, got '$_bk_ovl_time'" >&2
      return 1
      ;;
    "")
      echo "bk_emit_overlap: time value must be numeric, got ''" >&2
      return 1
      ;;
  esac
  # Must contain at least one digit
  case "$_bk_ovl_time" in
    *[0-9]*)
      ;;
    *)
      echo "bk_emit_overlap: time value must be numeric, got '$_bk_ovl_time'" >&2
      return 1
      ;;
  esac

  bk_emit_section "overlap:${_bk_ovl_sections}" "$_bk_ovl_time" "$_bk_ovl_package" "$_bk_ovl_artifact" --type overlap --members "$_bk_ovl_sections"
}

# bk_fetch_source - Fetch source code and collect metadata.
#
# Usage:
#   bk_fetch_source <source> <dest_dir> [branch]
#
# Arguments:
#   $1 - source: Repository URL or archive file path
#   $2 - dest_dir: Destination directory name
#   $3 - branch: (optional) Git branch to clone
#
# Auto-detection:
#   http:// / https:// prefix or .git suffix → git clone
#   Otherwise → tar archive extraction
#
# Environment variables set:
#   BK_SOURCE_TYPE  - "git" or "file"
#   BK_REPO_URL     - (git) Repository URL
#   BK_BRANCH       - (git) Branch name
#   BK_COMMIT_HASH  - (git) Full 40-char commit hash
#   BK_FILE_PATH    - (file) Absolute path to archive
#   BK_MD5SUM       - (file) Full 32-char md5sum
#
# Side effects:
#   Writes results/source_info.env in export format
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

    export BK_BRANCH BK_COMMIT_HASH

    # Write results/source_info.env
    cat > results/source_info.env <<EOF
export BK_SOURCE_TYPE="git"
export BK_REPO_URL="$BK_REPO_URL"
export BK_BRANCH="$BK_BRANCH"
export BK_COMMIT_HASH="$BK_COMMIT_HASH"
EOF

  else
    # --- File archive path ---
    BK_SOURCE_TYPE="file"
    export BK_SOURCE_TYPE

    # Check archive exists
    if [ ! -f "$_bk_src" ]; then
      echo "bk_fetch_source: archive file not found: '$_bk_src'" >&2
      return 1
    fi

    # Compute absolute path
    case "$_bk_src" in
      /*)
        BK_FILE_PATH="$_bk_src"
        ;;
      *)
        BK_FILE_PATH="$(pwd)/$_bk_src"
        ;;
    esac
    export BK_FILE_PATH

    # Cross-platform md5sum
    if command -v md5sum >/dev/null 2>&1; then
      BK_MD5SUM=$(md5sum "$_bk_src" | awk '{print $1}')
    elif command -v md5 >/dev/null 2>&1; then
      BK_MD5SUM=$(md5 -r "$_bk_src" | awk '{print $1}')
    else
      echo "bk_fetch_source: warning: neither md5sum nor md5 found" >&2
      BK_MD5SUM=""
    fi
    export BK_MD5SUM

    # Extract archive if dest_dir doesn't exist
    if [ ! -d "$_bk_dest" ]; then
      if ! tar -xzf "$_bk_src" -C "$(dirname "$_bk_dest")" 2>&1; then
        echo "bk_fetch_source: tar extraction failed for '$_bk_src'" >&2
        return 1
      fi
    fi

    # Write results/source_info.env
    cat > results/source_info.env <<EOF
export BK_SOURCE_TYPE="file"
export BK_FILE_PATH="$BK_FILE_PATH"
export BK_MD5SUM="$BK_MD5SUM"
EOF

  fi

  return 0
}
