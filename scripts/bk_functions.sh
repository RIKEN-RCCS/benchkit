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

  # Normalize scientific notation (e.g. 3.64E+01 -> 36.400) to plain decimal
  case "$_bk_fom" in
    *[eE]*)
      _bk_fom=$(awk "BEGIN {printf \"%.6g\", $_bk_fom}")
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
#
# Output format:
#   SECTION:<name> time:<time>
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

  echo "SECTION:${_bk_sec_name} time:${_bk_sec_time}"
  return 0
}

# bk_emit_overlap - Output a standardized OVERLAP timing line.
#
# Positional arguments:
#   $1 - comma-separated section names (required)
#   $2 - time value (required, numeric)
#
# Output format:
#   OVERLAP:<section_names> time:<time>
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

  echo "OVERLAP:${_bk_ovl_sections} time:${_bk_ovl_time}"
  return 0
}
