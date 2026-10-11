#!/bin/bash
# Artifact lookup shared by observation and estimation; no inference dependencies.

bk_estimation_section_key() {
  printf '%s\n' "$1" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g'
}

bk_estimation_artifact_file_exists() {
  local rel_path="$1"
  local root="${2:-}"

  [[ -n "$rel_path" ]] || return 1
  if [[ -f "$rel_path" ]]; then
    return 0
  fi
  if [[ -n "$root" && -f "${root}/${rel_path}" ]]; then
    return 0
  fi
  return 1
}

bk_estimation_resolve_section_artifact() {
  local env_prefix="$1"
  local root="$2"
  local section_name="$3"
  local section_key
  local env_var
  local explicit_artifact
  local candidate

  shift 3
  section_key=$(bk_estimation_section_key "$section_name")
  env_var="${env_prefix}_${section_key}_ARTIFACT"
  explicit_artifact="${!env_var:-}"
  if [[ -n "$explicit_artifact" ]]; then
    if bk_estimation_artifact_file_exists "$explicit_artifact" "$root"; then
      printf '%s\n' "$explicit_artifact"
      return 0
    fi
    echo "Section artifact was requested but not found: ${env_var}=${explicit_artifact}" >&2
    return 1
  fi

  for candidate in "$@"; do
    if bk_estimation_artifact_file_exists "$candidate" "$root"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}
