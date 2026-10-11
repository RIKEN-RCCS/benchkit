#!/bin/bash
# Shared function definitions; loaded by the appropriate Benchkit entrypoint.

# Profiler helpers
#
# Benchkit keeps the common wrapper in bk_functions.sh, while each application
# decides whether to use a profiler and which profiler tool / level to request.
# A level is translated per tool: fapp levels expand to one or more counter
# event runs, while ncu levels expand to a single Nsight Compute invocation with
# preset command-line options. Both tools stage raw data and meta.json in the
# same archive shape so result generation and the portal do not need to infer
# tool-specific filenames.
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
# BK_PROFILER_ARGS and BK_PROFILER_REPORT_ARGS are expanded as shell fragments
# because sites often need to pass multiple profiler flags from CI variables.
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

# fapp requires a separate profiler run for each counter group. The public
# level names stay stable even if the underlying pa* event set changes.
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

# Nsight Compute levels are intentionally short presets. Callers can append
# site- or application-specific flags with BK_PROFILER_ARGS.
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

bk_bool_enabled() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
  esac
  return 1
}

bk_profile_key() {
  printf '%s\n' "$1" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g'
}

bk_profile_slug() {
  _bk_profile_slug=$(printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_.-]/_/g; s/^_*//; s/_*$//')
  printf '%s\n' "${_bk_profile_slug:-profile}"
}

bk_resolve_profiler_tool() {
  _bk_profiler_default="${1:-none}"
  shift || true

  for _bk_profiler_var_name in "$@"; do
    [ -n "$_bk_profiler_var_name" ] || continue
    case "$_bk_profiler_var_name" in
      [!A-Za-z_]*|*[!A-Za-z0-9_]*)
        echo "bk_resolve_profiler_tool: invalid variable name '${_bk_profiler_var_name}'" >&2
        return 1
        ;;
    esac
    eval "_bk_profiler_candidate=\${${_bk_profiler_var_name}:-}"
    if [ -n "$_bk_profiler_candidate" ]; then
      bk_get_profiler_tool "$_bk_profiler_candidate"
      return $?
    fi
  done

  if [ -n "${BK_PROFILER:-}" ]; then
    bk_get_profiler_tool "$BK_PROFILER"
    return $?
  fi
  if [ -n "${BK_PROFILER_TOOL:-}" ]; then
    bk_get_profiler_tool "$BK_PROFILER_TOOL"
    return $?
  fi

  bk_get_profiler_tool "$_bk_profiler_default"
}

bk_resolve_profiler_level() {
  _bk_profiler_level_default="${1:-}"
  shift || true

  for _bk_profiler_var_name in "$@"; do
    [ -n "$_bk_profiler_var_name" ] || continue
    case "$_bk_profiler_var_name" in
      [!A-Za-z_]*|*[!A-Za-z0-9_]*)
        echo "bk_resolve_profiler_level: invalid variable name '${_bk_profiler_var_name}'" >&2
        return 1
        ;;
    esac
    eval "_bk_profiler_level_candidate=\${${_bk_profiler_var_name}:-}"
    if [ -n "$_bk_profiler_level_candidate" ]; then
      printf '%s\n' "$_bk_profiler_level_candidate"
      return 0
    fi
  done

  if [ -n "${BK_PROFILER_LEVEL:-}" ]; then
    printf '%s\n' "$BK_PROFILER_LEVEL"
    return 0
  fi

  printf '%s\n' "$_bk_profiler_level_default"
}
