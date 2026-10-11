#!/bin/bash
# Shared function definitions; loaded by the appropriate Benchkit entrypoint.

# bk_emit_section - Output a standardized SECTION timing line.
#
# Positional arguments:
#   $1 - section name (required)
#   $2 - time value (required, numeric)
#   $3 - estimation package name (optional)
#   $4 - auxiliary artifact path or comma-separated paths (optional)
#
# Optional named arguments:
#   --type <value>         (optional, default: regular)
#   --members <value>      (optional, comma-separated related sections for overlap-like entries)
#
# Output format:
#   SECTION:<name> time:<time> [type:<type>] [members:<members>]
#   [estimation_package:<package>] [artifact:<path>[,<path>...]]
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

# Version declarations are plain data; reading them never starts measurement.
bk_clear_observation_definitions() {
  BK_OBSERVATION_VERSION=""
  BK_SECTION_TIME_COLLECTOR=""
  BK_SECTION_TIME_UNIT=""
  BK_OBSERVATION_PROFILE_DECLARATIONS=""
}

bk_define_observation_version() {
  BK_OBSERVATION_VERSION="${1:-}"
}

bk_define_section_time_collector() {
  BK_SECTION_TIME_COLLECTOR="${1:-}"
}

bk_define_section_time_unit() {
  # The Result section contract records seconds.
  [[ "${1:-}" == s ]] || { echo "Section times must be converted to seconds" >&2; return 1; }
  BK_SECTION_TIME_UNIT=s
}

bk_define_profile() {
  [[ "$#" == 2 ]] || return 1
  BK_OBSERVATION_PROFILE_DECLARATIONS="${BK_OBSERVATION_PROFILE_DECLARATIONS:+${BK_OBSERVATION_PROFILE_DECLARATIONS}
}$1|$2"
}

# Emit within a FOM block so each Result keeps its own observation version.
bk_emit_observation_definition() {
  if [[ -n "${BK_OBSERVATION_VERSION:-}" ]]; then
    case "$BK_OBSERVATION_VERSION" in
      *[!a-zA-Z0-9._+-]*) echo "Invalid observation version" >&2; return 1 ;;
    esac
    printf 'OBSERVATION_VERSION:%s\n' "$BK_OBSERVATION_VERSION"
  fi
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
