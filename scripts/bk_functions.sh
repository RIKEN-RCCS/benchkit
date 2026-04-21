#!/bin/bash
# bk_functions.sh - Common functions for standardized benchmark result output.
# Source this file from BenchKit bash run/build/estimate scripts.
#
# Bash is required for the estimation and profiler helpers below.

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

# Estimation declaration helpers
#
# Applications can declare section/overlap to estimation-package bindings in
# estimate.sh, and run.sh can later emit measured values through that mapping.

bk_clear_estimation_declarations() {
  BK_ESTIMATION_DECLARATIONS=""
  BK_ESTIMATION_DECLARATIONS_CURRENT=""
  BK_ESTIMATION_DECLARATIONS_FUTURE=""
  export BK_ESTIMATION_DECLARATIONS
  export BK_ESTIMATION_DECLARATIONS_CURRENT
  export BK_ESTIMATION_DECLARATIONS_FUTURE
}

bk_clear_estimation_defaults() {
  BK_ESTIMATION_DECLARED_CURRENT_PACKAGE=""
  BK_ESTIMATION_DECLARED_FUTURE_PACKAGE=""
  BK_ESTIMATION_DECLARED_BASELINE_SYSTEM=""
  BK_ESTIMATION_DECLARED_BASELINE_EXP=""
  BK_ESTIMATION_DECLARED_FUTURE_SYSTEM=""
  BK_ESTIMATION_DECLARED_CURRENT_TARGET_NODES=""
  BK_ESTIMATION_DECLARED_FUTURE_TARGET_NODES=""
  export BK_ESTIMATION_DECLARED_CURRENT_PACKAGE
  export BK_ESTIMATION_DECLARED_FUTURE_PACKAGE
  export BK_ESTIMATION_DECLARED_BASELINE_SYSTEM
  export BK_ESTIMATION_DECLARED_BASELINE_EXP
  export BK_ESTIMATION_DECLARED_FUTURE_SYSTEM
  export BK_ESTIMATION_DECLARED_CURRENT_TARGET_NODES
  export BK_ESTIMATION_DECLARED_FUTURE_TARGET_NODES
}

bk_define_current_estimation_package() {
  BK_ESTIMATION_DECLARED_CURRENT_PACKAGE="${1:-}"
  export BK_ESTIMATION_DECLARED_CURRENT_PACKAGE
}

bk_define_future_estimation_package() {
  BK_ESTIMATION_DECLARED_FUTURE_PACKAGE="${1:-}"
  export BK_ESTIMATION_DECLARED_FUTURE_PACKAGE
}

bk_define_baseline_system() {
  BK_ESTIMATION_DECLARED_BASELINE_SYSTEM="${1:-}"
  export BK_ESTIMATION_DECLARED_BASELINE_SYSTEM
}

bk_define_baseline_exp() {
  BK_ESTIMATION_DECLARED_BASELINE_EXP="${1:-}"
  export BK_ESTIMATION_DECLARED_BASELINE_EXP
}

bk_define_future_system() {
  BK_ESTIMATION_DECLARED_FUTURE_SYSTEM="${1:-}"
  export BK_ESTIMATION_DECLARED_FUTURE_SYSTEM
}

bk_define_current_target_nodes() {
  BK_ESTIMATION_DECLARED_CURRENT_TARGET_NODES="${1:-}"
  export BK_ESTIMATION_DECLARED_CURRENT_TARGET_NODES
}

bk_define_future_target_nodes() {
  BK_ESTIMATION_DECLARED_FUTURE_TARGET_NODES="${1:-}"
  export BK_ESTIMATION_DECLARED_FUTURE_TARGET_NODES
}

bk_declare_section() {
  _bk_decl_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_declare_section: --side requires current or future" >&2
      return 1
    fi
    _bk_decl_side="$1"
    shift
  fi

  if [ $# -lt 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
    echo "bk_declare_section: requires <section_name> <estimation_package>" >&2
    return 1
  fi

  _bk_decl_name="$1"
  _bk_decl_package="$2"

  case "$_bk_decl_side" in
    current)
      _bk_decl_var="BK_ESTIMATION_DECLARATIONS_CURRENT"
      ;;
    future)
      _bk_decl_var="BK_ESTIMATION_DECLARATIONS_FUTURE"
      ;;
    *)
      echo "bk_declare_section: side must be current or future" >&2
      return 1
      ;;
  esac

  eval "_bk_decl_existing=\${$_bk_decl_var:-}"
  if [ -n "$_bk_decl_existing" ]; then
    _bk_decl_existing="${_bk_decl_existing}
section|${_bk_decl_name}|${_bk_decl_package}"
  else
    _bk_decl_existing="section|${_bk_decl_name}|${_bk_decl_package}"
  fi

  eval "$_bk_decl_var=\$_bk_decl_existing"
  BK_ESTIMATION_DECLARATIONS="$BK_ESTIMATION_DECLARATIONS_FUTURE"
  export "$_bk_decl_var"
  export BK_ESTIMATION_DECLARATIONS
}

bk_declare_overlap() {
  _bk_decl_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_declare_overlap: --side requires current or future" >&2
      return 1
    fi
    _bk_decl_side="$1"
    shift
  fi

  if [ $# -lt 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
    echo "bk_declare_overlap: requires <members> <estimation_package>" >&2
    return 1
  fi

  _bk_decl_members="$1"
  _bk_decl_package="$2"

  case "$_bk_decl_side" in
    current)
      _bk_decl_var="BK_ESTIMATION_DECLARATIONS_CURRENT"
      ;;
    future)
      _bk_decl_var="BK_ESTIMATION_DECLARATIONS_FUTURE"
      ;;
    *)
      echo "bk_declare_overlap: side must be current or future" >&2
      return 1
      ;;
  esac

  eval "_bk_decl_existing=\${$_bk_decl_var:-}"
  if [ -n "$_bk_decl_existing" ]; then
    _bk_decl_existing="${_bk_decl_existing}
overlap|${_bk_decl_members}|${_bk_decl_package}"
  else
    _bk_decl_existing="overlap|${_bk_decl_members}|${_bk_decl_package}"
  fi

  eval "$_bk_decl_var=\$_bk_decl_existing"
  BK_ESTIMATION_DECLARATIONS="$BK_ESTIMATION_DECLARATIONS_FUTURE"
  export "$_bk_decl_var"
  export BK_ESTIMATION_DECLARATIONS
}

bk_lookup_declared_estimation_package() {
  _bk_lookup_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_lookup_declared_estimation_package: --side requires current or future" >&2
      return 1
    fi
    _bk_lookup_side="$1"
    shift
  fi

  if [ $# -lt 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
    echo "bk_lookup_declared_estimation_package: requires <section|overlap> <key>" >&2
    return 1
  fi

  _bk_lookup_kind="$1"
  _bk_lookup_key="$2"

  case "$_bk_lookup_side" in
    current)
      _bk_lookup_declarations="${BK_ESTIMATION_DECLARATIONS_CURRENT:-}"
      ;;
    future)
      _bk_lookup_declarations="${BK_ESTIMATION_DECLARATIONS_FUTURE:-${BK_ESTIMATION_DECLARATIONS:-}}"
      ;;
    *)
      echo "bk_lookup_declared_estimation_package: side must be current or future" >&2
      return 1
      ;;
  esac

  if [ -z "$_bk_lookup_declarations" ]; then
    echo "bk_lookup_declared_estimation_package: no declarations found" >&2
    return 1
  fi

  _bk_lookup_result=$(printf '%s\n' "$_bk_lookup_declarations" | awk -F'|' -v kind="$_bk_lookup_kind" -v key="$_bk_lookup_key" '
    $1 == kind && $2 == key { print $3; found=1; exit }
    END { if (!found) exit 1 }
  ')
  _bk_lookup_status=$?

  if [ "$_bk_lookup_status" -ne 0 ] || [ -z "$_bk_lookup_result" ]; then
    echo "bk_lookup_declared_estimation_package: no declaration found for ${_bk_lookup_kind}:${_bk_lookup_key}" >&2
    return 1
  fi

  echo "$_bk_lookup_result"
}

bk_emit_declared_section() {
  _bk_decl_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_emit_declared_section: --side requires current or future" >&2
      return 1
    fi
    _bk_decl_side="$1"
    shift
  fi

  if [ $# -lt 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
    echo "bk_emit_declared_section: requires <section_name> <time> [artifact]" >&2
    return 1
  fi

  _bk_decl_sec_name="$1"
  _bk_decl_sec_time="$2"
  _bk_decl_sec_artifact="${3:-}"
  _bk_decl_sec_package=$(bk_lookup_declared_estimation_package --side "$_bk_decl_side" section "$_bk_decl_sec_name") || return 1

  bk_emit_section "$_bk_decl_sec_name" "$_bk_decl_sec_time" "$_bk_decl_sec_package" "$_bk_decl_sec_artifact"
}

bk_emit_declared_overlap() {
  _bk_decl_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_emit_declared_overlap: --side requires current or future" >&2
      return 1
    fi
    _bk_decl_side="$1"
    shift
  fi

  if [ $# -lt 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
    echo "bk_emit_declared_overlap: requires <members> <time> [artifact]" >&2
    return 1
  fi

  _bk_decl_ovl_members="$1"
  _bk_decl_ovl_time="$2"
  _bk_decl_ovl_artifact="${3:-}"
  _bk_decl_ovl_package=$(bk_lookup_declared_estimation_package --side "$_bk_decl_side" overlap "$_bk_decl_ovl_members") || return 1

  bk_emit_overlap "$_bk_decl_ovl_members" "$_bk_decl_ovl_time" "$_bk_decl_ovl_package" "$_bk_decl_ovl_artifact"
}

bk_list_declared_estimation_packages() {
  _bk_list_side="${1:-future}"
  case "$_bk_list_side" in
    current)
      _bk_list_declarations="${BK_ESTIMATION_DECLARATIONS_CURRENT:-}"
      ;;
    future)
      _bk_list_declarations="${BK_ESTIMATION_DECLARATIONS_FUTURE:-${BK_ESTIMATION_DECLARATIONS:-}}"
      ;;
    *)
      echo "bk_list_declared_estimation_packages: side must be current or future" >&2
      return 1
      ;;
  esac

  if [ -z "$_bk_list_declarations" ]; then
    return 0
  fi

  printf '%s\n' "$_bk_list_declarations" | awk -F'|' '!seen[$3]++ { print $3 }'
}

bk_load_estimation_section_package_impls() {
  local package_file

  for package_file in scripts/estimation/section_packages/*.sh; do
    [ -f "$package_file" ] || continue
    # shellcheck disable=SC1090
    . "$package_file"
  done
}

bk_section_package_requires_special_acquisition() {
  local package_name="$1"
  local fn_name
  local mode

  fn_name="bk_section_package_metadata_${package_name}"
  if ! declare -F "$fn_name" >/dev/null 2>&1; then
    return 1
  fi

  mode=$("$fn_name" | jq -r '.acquisition_mode // "standard"')
  [ "$mode" = "special" ]
}

# bk_run_estimation_data_collection - Common entrypoint for additional
# estimation-input collection runs.
#
# Positional arguments:
#   $@ - the full execution command after mpiexec/mpirun, or another launcher
#
# Default behavior:
#   Execute the command as-is.
#
# Extension point:
#   If bk_wrap_estimation_data_collection is defined, BenchKit calls it instead.
#   This allows package- or site-dependent wrappers such as ncu, profiler, or
#   hardware-counter tools to be inserted without pushing that logic into app
#   estimate.sh files.
bk_run_estimation_data_collection() {
  if [ $# -eq 0 ]; then
    echo "bk_run_estimation_data_collection: requires an execution command" >&2
    return 1
  fi

  bk_load_estimation_section_package_impls

  _bk_special_packages=""
  for _bk_decl_package in $(bk_list_declared_estimation_packages); do
    if bk_section_package_requires_special_acquisition "$_bk_decl_package"; then
      if [ -n "$_bk_special_packages" ]; then
        _bk_special_packages="${_bk_special_packages},${_bk_decl_package}"
      else
        _bk_special_packages="$_bk_decl_package"
      fi
    fi
  done

  if [ -z "$_bk_special_packages" ]; then
    return 0
  fi

  if declare -F bk_wrap_estimation_data_collection >/dev/null 2>&1; then
    bk_wrap_estimation_data_collection "$_bk_special_packages" -- "$@"
    return $?
  fi

  echo "bk_run_estimation_data_collection: special acquisition required by ${_bk_special_packages}, but no wrapper is defined" >&2
  return 1
}

# Profiler helpers
#
# BenchKit keeps the common wrapper in bk_functions.sh, while each application
# decides whether to use a profiler and which profiler tool / level to request.
#
# Positional arguments:
#   $1 - profiler tool (empty|none|off|fapp|ncu)
#
# Supported variables:
#   BK_PROFILER_LEVEL          optional profiler level override
#   BK_PROFILER_REPORT_FORMAT  optional report format override
#   BK_PROFILER_ARGS           optional extra measurement flags
#   BK_PROFILER_REPORT_ARGS    optional extra postprocess flags
#   BK_PROFILER_DIR            raw profile output dir (default: pa)
#   BK_PROFILER_STAGE_DIR      temporary staging dir for archive creation
bk_get_profiler_tool() {
  _bk_profiler_tool="${1:-}"
  case "$_bk_profiler_tool" in
    ""|none|off)
      printf '%s\n' ""
      return 0
      ;;
    fapp|ncu)
      printf '%s\n' "$_bk_profiler_tool"
      return 0
      ;;
    *)
      echo "bk_get_profiler_tool: unsupported profiler '${_bk_profiler_tool}'" >&2
      return 1
      ;;
  esac
}

bk_profiler_enabled() {
  _bk_profiler_tool=$(bk_get_profiler_tool "$1") || return 1
  [ -n "$_bk_profiler_tool" ]
}

bk_get_profiler_level() {
  _bk_profiler_tool=$(bk_get_profiler_tool "$1") || return 1
  _bk_profiler_level="${2:-}"

  if [ -z "$_bk_profiler_tool" ]; then
    printf '%s\n' ""
    return 0
  fi

  if [ -z "$_bk_profiler_level" ]; then
    case "$_bk_profiler_tool" in
      fapp)
        _bk_profiler_level="single"
        ;;
      ncu)
        _bk_profiler_level="single"
        ;;
    esac
  fi

  case "$_bk_profiler_tool:${_bk_profiler_level}" in
    fapp:single|fapp:simple|fapp:standard|fapp:detailed)
      printf '%s\n' "$_bk_profiler_level"
      return 0
      ;;
    ncu:single|ncu:simple|ncu:standard|ncu:detailed)
      printf '%s\n' "$_bk_profiler_level"
      return 0
      ;;
    *)
      echo "bk_get_profiler_level: unsupported level '${_bk_profiler_level}' for tool '${_bk_profiler_tool}'" >&2
      return 1
      ;;
  esac
}

bk_get_profiler_report_format() {
  _bk_profiler_tool=$(bk_get_profiler_tool "$1") || return 1
  _bk_profiler_level=$(bk_get_profiler_level "$_bk_profiler_tool" "$2") || return 1
  _bk_profiler_report_format="${3:-}"

  if [ -z "$_bk_profiler_tool" ]; then
    printf '%s\n' ""
    return 0
  fi

  if [ -z "$_bk_profiler_report_format" ]; then
    case "$_bk_profiler_tool:${_bk_profiler_level}" in
      fapp:single)
        _bk_profiler_report_format="text"
        ;;
      fapp:simple|fapp:standard|fapp:detailed)
        _bk_profiler_report_format="both"
        ;;
      ncu:single|ncu:simple|ncu:standard|ncu:detailed)
        _bk_profiler_report_format="text"
        ;;
    esac
  fi

  case "$_bk_profiler_report_format" in
    text|csv|both)
      printf '%s\n' "$_bk_profiler_report_format"
      return 0
      ;;
    *)
      echo "bk_get_profiler_report_format: unsupported report format '${_bk_profiler_report_format}'" >&2
      return 1
      ;;
  esac
}

bk_profiler_fapp_level_events() {
  case "$1" in
    single)
      printf '%s\n' "pa1"
      ;;
    simple)
      printf '%s\n' "pa1 pa2 pa3 pa4 pa5"
      ;;
    standard)
      printf '%s\n' "pa1 pa2 pa3 pa4 pa5 pa6 pa7 pa8 pa9 pa10 pa11"
      ;;
    detailed)
      printf '%s\n' "pa1 pa2 pa3 pa4 pa5 pa6 pa7 pa8 pa9 pa10 pa11 pa12 pa13 pa14 pa15 pa16 pa17"
      ;;
    *)
      echo "bk_profiler_fapp_level_events: unsupported level '$1'" >&2
      return 1
      ;;
  esac
}

bk_profiler_fapp_postprocess_command() {
  if command -v fapppx >/dev/null 2>&1; then
    printf '%s\n' "fapppx"
    return 0
  fi

  if command -v fapp >/dev/null 2>&1; then
    printf '%s\n' "fapp"
    return 0
  fi

  return 1
}

bk_profiler_ncu_level_args() {
  case "$1" in
    single)
      printf '%s\n' "--set basic --launch-count 1"
      ;;
    simple)
      printf '%s\n' "--set basic --launch-count 5"
      ;;
    standard)
      printf '%s\n' "--set full --launch-count 1"
      ;;
    detailed)
      printf '%s\n' "--set full --nvtx"
      ;;
    *)
      echo "bk_profiler_ncu_level_args: unsupported level '$1'" >&2
      return 1
      ;;
  esac
}

bk_profiler_find_ncu_report() {
  _bk_ncu_report_dir="$1"
  find "$_bk_ncu_report_dir" -maxdepth 1 -type f \( \
    -name '*.ncu-rep' -o \
    -name '*.nsight-cuprof' -o \
    -name 'profile*' \
  \) | head -n 1
}

bk_json_escape() {
  _bk_json_value="$1"
  _bk_json_value=${_bk_json_value//\\/\\\\}
  _bk_json_value=${_bk_json_value//\"/\\\"}
  _bk_json_value=${_bk_json_value//$'\t'/\\t}
  _bk_json_value=${_bk_json_value//$'\r'/\\r}
  _bk_json_value=${_bk_json_value//$'\n'/\\n}
  printf '%s' "$_bk_json_value"
}

bk_json_string() {
  printf '"'
  bk_json_escape "$1"
  printf '"'
}

bk_json_string_array() {
  _bk_json_first=1
  printf '['
  for _bk_json_item in "$@"; do
    if [ "$_bk_json_first" -eq 0 ]; then
      printf ', '
    fi
    bk_json_string "$_bk_json_item"
    _bk_json_first=0
  done
  printf ']'
}

bk_profiler_write_meta() {
  _bk_meta_stage_dir="$1"
  _bk_meta_tool="$2"
  _bk_meta_level="$3"
  _bk_meta_report_format="$4"
  _bk_meta_run_names="$5"
  _bk_meta_run_events="$6"
  _bk_meta_profiler_args="$7"
  _bk_meta_report_args="$8"
  _bk_meta_file="${_bk_meta_stage_dir}/meta.json"
  IFS=',' read -r -a _bk_meta_names <<< "$_bk_meta_run_names"
  IFS=',' read -r -a _bk_meta_events <<< "$_bk_meta_run_events"

  {
    printf '{\n'
    printf '  "tool": "%s",\n' "$_bk_meta_tool"
    printf '  "level": "%s",\n' "$_bk_meta_level"
    printf '  "report_format": "%s",\n' "$_bk_meta_report_format"
    printf '  "raw_dir": "raw",\n'
    printf '  "measurement": {\n'
    printf '    "run_count": %s,\n' "${#_bk_meta_names[@]}"
    printf '    "profiler_args": '
    bk_json_string "$_bk_meta_profiler_args"
    printf ',\n'
    printf '    "report_args": '
    bk_json_string "$_bk_meta_report_args"
    case "$_bk_meta_tool" in
      fapp)
        printf ',\n'
        printf '    "fapp_events": '
        bk_json_string_array "${_bk_meta_events[@]}"
        printf '\n'
        ;;
      ncu)
        _bk_meta_ncu_level_args=$(bk_profiler_ncu_level_args "$_bk_meta_level")
        read -r -a _bk_meta_ncu_level_arg_array <<< "$_bk_meta_ncu_level_args"
        printf ',\n'
        printf '    "ncu_options": '
        bk_json_string_array "--target-processes" "all" "${_bk_meta_ncu_level_arg_array[@]}"
        printf '\n'
        ;;
      *)
        printf '\n'
        ;;
    esac
    printf '  },\n'
    printf '  "runs": [\n'
    for _bk_meta_idx in "${!_bk_meta_names[@]}"; do
      _bk_meta_name="${_bk_meta_names[$_bk_meta_idx]}"
      _bk_meta_event="${_bk_meta_events[$_bk_meta_idx]:-}"
      case "$_bk_meta_tool" in
        fapp)
          _bk_meta_text_path="reports/fapp_A_${_bk_meta_name}.txt"
          _bk_meta_csv_path="reports/cpu_pa_${_bk_meta_name}.csv"
          _bk_meta_text_abs="${_bk_meta_stage_dir}/${_bk_meta_text_path}"
          _bk_meta_csv_abs="${_bk_meta_stage_dir}/${_bk_meta_csv_path}"
          _bk_meta_ncu_report_path=""
          _bk_meta_ncu_report_abs=""
          ;;
        ncu)
          _bk_meta_text_path="reports/ncu_import_${_bk_meta_name}.txt"
          _bk_meta_csv_path=""
          _bk_meta_text_abs="${_bk_meta_stage_dir}/${_bk_meta_text_path}"
          _bk_meta_csv_abs=""
          _bk_meta_ncu_report_abs=$(bk_profiler_find_ncu_report "${_bk_meta_stage_dir}/raw/${_bk_meta_name}" || true)
          if [ -n "$_bk_meta_ncu_report_abs" ]; then
            _bk_meta_ncu_report_path="${_bk_meta_ncu_report_abs#${_bk_meta_stage_dir}/}"
          else
            _bk_meta_ncu_report_path=""
          fi
          ;;
        *)
          _bk_meta_text_path=""
          _bk_meta_csv_path=""
          _bk_meta_text_abs=""
          _bk_meta_csv_abs=""
          _bk_meta_ncu_report_path=""
          _bk_meta_ncu_report_abs=""
          ;;
      esac

      printf '    {\n'
      printf '      "name": "%s",\n' "$_bk_meta_name"
      printf '      "event": "%s",\n' "$_bk_meta_event"
      printf '      "raw_path": "raw/%s",\n' "$_bk_meta_name"
      printf '      "measurement": {\n'
      case "$_bk_meta_tool" in
        fapp)
          printf '        "counter": '
          bk_json_string "$_bk_meta_event"
          printf ',\n'
          printf '        "options": '
          bk_json_string_array "-C" "-d" "raw/${_bk_meta_name}" "-Hevent=${_bk_meta_event}"
          printf '\n'
          ;;
        ncu)
          _bk_meta_ncu_level_args=$(bk_profiler_ncu_level_args "$_bk_meta_level")
          read -r -a _bk_meta_ncu_level_arg_array <<< "$_bk_meta_ncu_level_args"
          printf '        "options": '
          bk_json_string_array "-o" "raw/${_bk_meta_name}/profile" "--target-processes" "all" "${_bk_meta_ncu_level_arg_array[@]}"
          printf '\n'
          ;;
        *)
          printf '        "options": []\n'
          ;;
      esac
      printf '      },\n'
      printf '      "reports": [\n'
      _bk_meta_has_report=0
      if [ -f "$_bk_meta_text_abs" ]; then
        printf '        {"kind": "summary_text", "path": "%s"}' "$_bk_meta_text_path"
        _bk_meta_has_report=1
      fi
      if [ -f "$_bk_meta_csv_abs" ]; then
        if [ "$_bk_meta_has_report" -eq 1 ]; then
          printf ',\n'
        fi
        printf '        {"kind": "cpu_pa_csv", "path": "%s"}' "$_bk_meta_csv_path"
        _bk_meta_has_report=1
      fi
      if [ -n "$_bk_meta_ncu_report_path" ] && [ -f "$_bk_meta_ncu_report_abs" ]; then
        if [ "$_bk_meta_has_report" -eq 1 ]; then
          printf ',\n'
        fi
        printf '        {"kind": "ncu_report", "path": "%s"}' "$_bk_meta_ncu_report_path"
        _bk_meta_has_report=1
      fi
      if [ "$_bk_meta_has_report" -eq 1 ]; then
        printf '\n'
      fi
      printf '      ]\n'
      if [ "$_bk_meta_idx" -lt "$(( ${#_bk_meta_names[@]} - 1 ))" ]; then
        printf '    },\n'
      else
        printf '    }\n'
      fi
    done
    printf '  ]\n'
    printf '}\n'
  } > "$_bk_meta_file"
}

bk_profiler_call_optional_hook() {
  _bk_hook_name="$1"
  shift || true

  if declare -F "$_bk_hook_name" >/dev/null 2>&1; then
    "$_bk_hook_name" "$@"
  fi
}

bk_profiler() {
  if [ $# -lt 2 ]; then
    echo "bk_profiler: requires a profiler tool and an execution command" >&2
    return 1
  fi

  _bk_profiler_tool=$(bk_get_profiler_tool "$1") || return 1
  shift
  _bk_profiler_archive="${BK_PROFILER_ARCHIVE:-results/padata.tgz}"
  _bk_profiler_dir="${BK_PROFILER_DIR:-pa}"
  _bk_profiler_level="${BK_PROFILER_LEVEL:-}"
  _bk_profiler_report_format="${BK_PROFILER_REPORT_FORMAT:-}"

  while [ $# -gt 0 ]; do
    case "$1" in
      --level)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --level requires a value" >&2
          return 1
        fi
        _bk_profiler_level="$1"
        ;;
      --report-format)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --report-format requires a value" >&2
          return 1
        fi
        _bk_profiler_report_format="$1"
        ;;
      --archive)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --archive requires a value" >&2
          return 1
        fi
        _bk_profiler_archive="$1"
        ;;
      --raw-dir)
        shift
        if [ $# -eq 0 ]; then
          echo "bk_profiler: --raw-dir requires a value" >&2
          return 1
        fi
        _bk_profiler_dir="$1"
        ;;
      --)
        shift
        break
        ;;
      *)
        break
        ;;
    esac
    shift
  done

  if [ $# -eq 0 ]; then
    echo "bk_profiler: requires an execution command" >&2
    return 1
  fi

  if [ -z "$_bk_profiler_tool" ]; then
    "$@"
    return $?
  fi

  _bk_profiler_level=$(bk_get_profiler_level "$_bk_profiler_tool" "$_bk_profiler_level") || return 1
  _bk_profiler_report_format=$(bk_get_profiler_report_format "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_profiler_report_format") || return 1

  rm -rf "$_bk_profiler_dir"
  mkdir -p "$_bk_profiler_dir"

  _bk_stage_dir="${BK_PROFILER_STAGE_DIR:-bk_profiler_artifact}"
  rm -rf "$_bk_stage_dir"
  mkdir -p "$_bk_stage_dir"
  mkdir -p "$_bk_stage_dir/raw"
  mkdir -p "$_bk_stage_dir/reports"
  _bk_profiler_run_names=""
  _bk_profiler_run_events=""
  _bk_profiler_status=0
  _bk_profiler_extra_args="${BK_PROFILER_ARGS:-}"
  _bk_profiler_report_extra_args="${BK_PROFILER_REPORT_ARGS:-}"

  case "$_bk_profiler_tool" in
    fapp)
      export FLIB_FASTOMP="${FLIB_FASTOMP:-TRUE}"
      read -r -a _bk_fapp_events <<< "$(bk_profiler_fapp_level_events "$_bk_profiler_level")"
      _bk_fapp_run_index=1
      for _bk_fapp_event in "${_bk_fapp_events[@]}"; do
        _bk_fapp_rep_name="rep${_bk_fapp_run_index}"
        _bk_fapp_rep_dir="${_bk_profiler_dir}/${_bk_fapp_rep_name}"
        mkdir -p "$_bk_fapp_rep_dir"
        echo "bk_profiler[fapp]: starting ${_bk_fapp_rep_name} event=${_bk_fapp_event}" >&2
        bk_profiler_call_optional_hook bk_profiler_before_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_fapp_rep_name" "$_bk_fapp_event" "$@" || return 1
        # shellcheck disable=SC2086
        if fapp -C -d "$_bk_fapp_rep_dir" ${_bk_profiler_extra_args} -Hevent="${_bk_fapp_event}" "$@"; then
          _bk_fapp_status=0
        else
          _bk_fapp_status=$?
        fi
        bk_profiler_call_optional_hook bk_profiler_after_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_fapp_rep_name" "$_bk_fapp_event" "$@" || return 1
        if [ "$_bk_fapp_status" -eq 0 ]; then
          echo "bk_profiler[fapp]: completed ${_bk_fapp_rep_name} event=${_bk_fapp_event}" >&2
        else
          echo "bk_profiler[fapp]: failed ${_bk_fapp_rep_name} event=${_bk_fapp_event} status=${_bk_fapp_status}" >&2
          _bk_profiler_status="$_bk_fapp_status"
        fi
        cp -R "$_bk_fapp_rep_dir" "$_bk_stage_dir/raw/${_bk_fapp_rep_name}"
        if [ -n "$_bk_profiler_run_names" ]; then
          _bk_profiler_run_names="${_bk_profiler_run_names},${_bk_fapp_rep_name}"
          _bk_profiler_run_events="${_bk_profiler_run_events},${_bk_fapp_event}"
        else
          _bk_profiler_run_names="${_bk_fapp_rep_name}"
          _bk_profiler_run_events="${_bk_fapp_event}"
        fi
        _bk_fapp_run_index=$((_bk_fapp_run_index + 1))
        if [ "$_bk_fapp_status" -ne 0 ]; then
          break
        fi
      done
      ;;
    ncu)
      if ! command -v ncu >/dev/null 2>&1; then
        echo "bk_profiler[ncu]: ncu not found in PATH" >&2
        return 1
      fi
      _bk_ncu_rep_name="rep1"
      _bk_ncu_rep_dir="${_bk_profiler_dir}/${_bk_ncu_rep_name}"
      _bk_ncu_profile_base="${_bk_ncu_rep_dir}/profile"
      mkdir -p "$_bk_ncu_rep_dir"
      _bk_ncu_level_args=$(bk_profiler_ncu_level_args "$_bk_profiler_level") || return 1
      echo "bk_profiler[ncu]: starting ${_bk_ncu_rep_name} level=${_bk_profiler_level}" >&2
      bk_profiler_call_optional_hook bk_profiler_before_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_ncu_rep_name" "$_bk_profiler_level" "$@" || return 1
      # shellcheck disable=SC2086
      if ncu -o "$_bk_ncu_profile_base" --target-processes all ${_bk_ncu_level_args} ${_bk_profiler_extra_args} "$@"; then
        _bk_profiler_status=0
      else
        _bk_profiler_status=$?
      fi
      bk_profiler_call_optional_hook bk_profiler_after_run "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_ncu_rep_name" "$_bk_profiler_level" "$@" || return 1
      if [ "$_bk_profiler_status" -eq 0 ]; then
        echo "bk_profiler[ncu]: completed ${_bk_ncu_rep_name} level=${_bk_profiler_level}" >&2
      else
        echo "bk_profiler[ncu]: failed ${_bk_ncu_rep_name} level=${_bk_profiler_level} status=${_bk_profiler_status}" >&2
      fi
      cp -R "$_bk_ncu_rep_dir" "$_bk_stage_dir/raw/${_bk_ncu_rep_name}"
      _bk_profiler_run_names="${_bk_ncu_rep_name}"
      _bk_profiler_run_events="${_bk_profiler_level}"
      ;;
  esac

  case "$_bk_profiler_tool" in
    fapp)
      if _bk_fapp_post_cmd=$(bk_profiler_fapp_postprocess_command); then
        export FLIB_FASTOMP="${FLIB_FASTOMP:-TRUE}"
        IFS=',' read -r -a _bk_fapp_run_name_list <<< "$_bk_profiler_run_names"
        for _bk_fapp_rep_name in "${_bk_fapp_run_name_list[@]}"; do
          _bk_fapp_rep_dir="${_bk_profiler_dir}/${_bk_fapp_rep_name}"
          if [ "$_bk_profiler_report_format" = "text" ] || [ "$_bk_profiler_report_format" = "both" ]; then
            # shellcheck disable=SC2086
            "$_bk_fapp_post_cmd" -A -d "$_bk_fapp_rep_dir" ${_bk_profiler_report_extra_args} > "$_bk_stage_dir/reports/fapp_A_${_bk_fapp_rep_name}.txt" 2>&1 || true
          fi
          if [ "$_bk_profiler_report_format" = "csv" ] || [ "$_bk_profiler_report_format" = "both" ]; then
            # shellcheck disable=SC2086
            "$_bk_fapp_post_cmd" -A -d "$_bk_fapp_rep_dir" ${_bk_profiler_report_extra_args} -Icpupa -tcsv -o "$_bk_stage_dir/reports/cpu_pa_${_bk_fapp_rep_name}.csv" >/dev/null 2>&1 || true
          fi
        done
      else
        echo "fapp/fapppx not found in PATH" > "$_bk_stage_dir/reports/fapp_A_missing.txt"
      fi
      ;;
    ncu)
      IFS=',' read -r -a _bk_ncu_run_name_list <<< "$_bk_profiler_run_names"
      for _bk_ncu_rep_name in "${_bk_ncu_run_name_list[@]}"; do
        _bk_ncu_report_file=$(bk_profiler_find_ncu_report "$_bk_profiler_dir/${_bk_ncu_rep_name}" || true)
        if [ -n "$_bk_ncu_report_file" ] && { [ "$_bk_profiler_report_format" = "text" ] || [ "$_bk_profiler_report_format" = "both" ]; }; then
          # shellcheck disable=SC2086
          ncu --import "$_bk_ncu_report_file" --page details ${_bk_profiler_report_extra_args} > "$_bk_stage_dir/reports/ncu_import_${_bk_ncu_rep_name}.txt" 2>&1 || true
        fi
      done
      ;;
  esac

  bk_profiler_write_meta "$_bk_stage_dir" "$_bk_profiler_tool" "$_bk_profiler_level" "$_bk_profiler_report_format" "$_bk_profiler_run_names" "$_bk_profiler_run_events" "$_bk_profiler_extra_args" "$_bk_profiler_report_extra_args"
  if tar -czf "$_bk_profiler_archive" "$_bk_stage_dir"; then
    _bk_profiler_archive_status=0
  else
    _bk_profiler_archive_status=$?
  fi
  rm -rf "$_bk_stage_dir"
  if [ "$_bk_profiler_archive_status" -ne 0 ]; then
    return "$_bk_profiler_archive_status"
  fi
  return "$_bk_profiler_status"
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
