#!/bin/bash
# Shared function definitions; loaded by the appropriate Benchkit entrypoint.

bk_define_estimation_method_version() {
  BK_APP_ESTIMATION_METHOD_VERSION="${1:-}"
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
  BK_APP_ESTIMATION_METHOD_VERSION=""
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
  _bk_decl_profile_suffix="${3:+|$3}"

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
section|${_bk_decl_name}|${_bk_decl_package}${_bk_decl_profile_suffix}"
  else
    _bk_decl_existing="section|${_bk_decl_name}|${_bk_decl_package}${_bk_decl_profile_suffix}"
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
  _bk_decl_profile_suffix="${3:+|$3}"

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
overlap|${_bk_decl_members}|${_bk_decl_package}${_bk_decl_profile_suffix}"
  else
    _bk_decl_existing="overlap|${_bk_decl_members}|${_bk_decl_package}${_bk_decl_profile_suffix}"
  fi

  eval "$_bk_decl_var=\$_bk_decl_existing"
  BK_ESTIMATION_DECLARATIONS="$BK_ESTIMATION_DECLARATIONS_FUTURE"
  export "$_bk_decl_var"
  export BK_ESTIMATION_DECLARATIONS
}

bk_declare_estimation_items() {
  _bk_decl_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_declare_estimation_items: --side requires current or future" >&2
      return 1
    fi
    _bk_decl_side="$1"
    shift
  fi

  if [ $# -ne 1 ] || [ -z "$1" ]; then
    echo "bk_declare_estimation_items: requires a newline-separated declaration list" >&2
    return 1
  fi

  while IFS='|' read -r _bk_decl_kind _bk_decl_name _bk_decl_package _bk_decl_profile; do
    [ -n "$_bk_decl_kind$_bk_decl_name$_bk_decl_package" ] || continue
    case "$_bk_decl_kind" in
      section)
        bk_declare_section --side "$_bk_decl_side" "$_bk_decl_name" "$_bk_decl_package" "$_bk_decl_profile"
        ;;
      overlap)
        bk_declare_overlap --side "$_bk_decl_side" "$_bk_decl_name" "$_bk_decl_package" "$_bk_decl_profile"
        ;;
      \#*)
        ;;
      *)
        echo "bk_declare_estimation_items: unsupported item kind '${_bk_decl_kind}'" >&2
        return 1
        ;;
    esac
  done <<EOF
$1
EOF
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

bk_emit_declared_timing_items() {
  _bk_decl_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_emit_declared_timing_items: --side requires current or future" >&2
      return 1
    fi
    _bk_decl_side="$1"
    shift
  fi

  if [ $# -ne 1 ] || [ -z "$1" ]; then
    echo "bk_emit_declared_timing_items: requires a newline-separated item list" >&2
    return 1
  fi

  while IFS='|' read -r _bk_decl_kind _bk_decl_name _bk_decl_time _bk_decl_artifact; do
    [ -n "$_bk_decl_kind$_bk_decl_name$_bk_decl_time$_bk_decl_artifact" ] || continue
    case "$_bk_decl_kind" in
      section)
        bk_emit_declared_section --side "$_bk_decl_side" "$_bk_decl_name" "$_bk_decl_time" "$_bk_decl_artifact"
        ;;
      overlap)
        bk_emit_declared_overlap --side "$_bk_decl_side" "$_bk_decl_name" "$_bk_decl_time" "$_bk_decl_artifact"
        ;;
      \#*)
        ;;
      *)
        echo "bk_emit_declared_timing_items: unsupported item kind '${_bk_decl_kind}'" >&2
        return 1
        ;;
    esac
  done <<EOF
$1
EOF
}

bk_emit_declared_fractional_items() {
  _bk_decl_side="future"
  if [ $# -gt 1 ] && [ "$1" = "--side" ]; then
    shift
    if [ $# -eq 0 ]; then
      echo "bk_emit_declared_fractional_items: --side requires current or future" >&2
      return 1
    fi
    _bk_decl_side="$1"
    shift
  fi

  if [ $# -ne 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
    echo "bk_emit_declared_fractional_items: requires <total_time> <newline-separated fractional item list>" >&2
    return 1
  fi

  _bk_decl_total_time="$1"
  _bk_decl_timing_items=""
  while IFS='|' read -r _bk_decl_kind _bk_decl_name _bk_decl_fraction _bk_decl_artifact; do
    [ -n "$_bk_decl_kind$_bk_decl_name$_bk_decl_fraction$_bk_decl_artifact" ] || continue
    case "$_bk_decl_kind" in
      section|overlap)
        _bk_decl_time=$(awk -v total="$_bk_decl_total_time" -v fraction="$_bk_decl_fraction" 'BEGIN {printf "%.3f", total * fraction}')
        if [ -n "$_bk_decl_timing_items" ]; then
          _bk_decl_timing_items="${_bk_decl_timing_items}
${_bk_decl_kind}|${_bk_decl_name}|${_bk_decl_time}|${_bk_decl_artifact}"
        else
          _bk_decl_timing_items="${_bk_decl_kind}|${_bk_decl_name}|${_bk_decl_time}|${_bk_decl_artifact}"
        fi
        ;;
      \#*)
        ;;
      *)
        echo "bk_emit_declared_fractional_items: unsupported item kind '${_bk_decl_kind}'" >&2
        return 1
        ;;
    esac
  done <<EOF
$2
EOF

  bk_emit_declared_timing_items --side "$_bk_decl_side" "$_bk_decl_timing_items"
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
#   If bk_wrap_estimation_data_collection is defined, Benchkit calls it instead.
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
