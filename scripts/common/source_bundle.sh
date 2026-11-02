#!/bin/bash
# Build a runtime payload and its provenance together; no JSON parser on compute hosts.

# Parse declarations as data, never source/eval them. Build and cache share this reader.
bk_source_request() {
  local file="$1" key variable value
  local values=()
  for key in repo_url ref commit; do
    value=$(bk_env_file_value "$file" "$key")
    variable=$(bk_env_file_value "$file" "${key}_env")
    if [ -n "$variable" ]; then
      [[ "$variable" =~ ^[a-zA-Z_][a-zA-Z_0-9]*$ ]] || return 2
      value="${!variable:-$value}"
    fi
    values+=("$value")
  done
  BK_SOURCE_REPO="${values[0]}" BK_SOURCE_REF="${values[1]:-main}"
  BK_SOURCE_COMMIT="${BK_FETCH_EXPECTED_COMMIT:-${values[2]}}"
  [ -n "$BK_SOURCE_REPO" ] || return 2
}

bk_build_declared_source() {
  bk_source_request "$1" || return $?
  bk_build_source "$BK_SOURCE_REPO" "$BK_SOURCE_REF" "$BK_SOURCE_COMMIT"
}

_bk_bundle_records() {
  local record separator=""
  printf '['
  while IFS= read -r record; do
    [ -n "$record" ] || continue
    printf '%s%s' "$separator" "$record"
    separator=,
  done < "$1"
  printf ']'
}

_bk_bundle_text_sha256() (
  set -euo pipefail
  printf '%s' "$1" | sha256sum | awk '{print $1}'
)

_bk_bundle_path() {
  case "$1" in
    ""|/*|.|..|../*|*/../*|*/..|.git|.git/*) return 1 ;;
  esac
}

_bk_source_path() {
  _bk_bundle_path "$1" || return 1
  case "$(realpath -m "$BK_SOURCE_DIR/$1")" in "$BK_SOURCE_DIR"/*) ;; *) return 1 ;; esac
}

# The inventory covers names, modes and bytes, and rejects links and special files.
_bk_bundle_inventory() (
  set -euo pipefail
  cd "$1"
  local path files mode hash
  files=$(mktemp)
  trap 'rm -f "$files"' EXIT
  find . -mindepth 1 -print0 | LC_ALL=C sort -z > "$files"
  while IFS= read -r -d '' path; do
    [ ! -L "$path" ] || exit 1
    [ "$path" != ./inventory ] || continue
    mode=$(stat -c '%a' "$path") || exit 1
    if [ -d "$path" ]; then
      printf 'D %s %s\n' "$mode" "$(bk_base64_encode_value "$path")"
    elif [ -f "$path" ]; then
      hash=$(bk_sha256_file "$path") || exit 1
      printf 'F %s %s %s\n' "$mode" "$hash" "$(bk_base64_encode_value "$path")"
    else
      exit 1
    fi
  done < "$files"
)

_bk_build_provenance() {
  local sha temporary
  sha=$(bk_sha256_file "$_BK_BUNDLE_SOURCE_INFO") || return 1
  temporary=$(mktemp "$_BK_BUNDLE_RESULTS/.build-provenance.XXXXXXXX") || return 1
  if bk_json_object json schema_version 1 \
    string source_info_sha256 "$sha" \
    json adjustments "$(_bk_bundle_records "$_BK_BUNDLE_STATE/adjustments")" \
    json variants "$(_bk_bundle_records "$_BK_BUNDLE_STATE/variants")" \
    > "$temporary"; then
    mv -- "$temporary" "$_BK_BUNDLE_RESULTS/build_provenance.json" && return 0
  fi
  rm -f "$temporary"
  return 1
}

# A new checkout is always private to this build; previous workspaces are untouched.
bk_build_source() {
  source "${BK_BENCHKIT_ROOT}/scripts/json_output.sh" || return 1
  local repo="$1" ref="${2:-main}" expected="${BK_FETCH_EXPECTED_COMMIT:-${3:-}}"
  local commit file state kind=branch resolved_ref="$ref"
  _BK_BUNDLE_ROOT="$PWD"
  _BK_BUNDLE_RESULTS="$PWD/results"
  mkdir -p "$_BK_BUNDLE_RESULTS" "$PWD/artifacts" || return 1
  [ ! -L "$PWD/artifacts" ] || return 1
  _BK_BUNDLE_STATE=$(mktemp -d "$PWD/.source-build.XXXXXXXX") || return 1
  _BK_BUNDLE_FAILED=0
  BK_SOURCE_DIR="$_BK_BUNDLE_STATE/source"
  _BK_BUNDLE_SOURCE_INFO="$_BK_BUNDLE_STATE/source_info.env"
  : > "$_BK_BUNDLE_STATE/adjustments"
  : > "$_BK_BUNDLE_STATE/variants"
  mkdir "$_BK_BUNDLE_STATE/payload" || return 1
  for file in source_info.env build_provenance.json; do
    if [ -e "$_BK_BUNDLE_RESULTS/$file" ] || [ -L "$_BK_BUNDLE_RESULTS/$file" ]; then
      [ -f "$_BK_BUNDLE_RESULTS/$file" ] && [ ! -L "$_BK_BUNDLE_RESULTS/$file" ] || return 1
      mv -- "$_BK_BUNDLE_RESULTS/$file" "$_BK_BUNDLE_STATE/previous-$file" || return 1
    fi
  done
  # Do not leave a previous build advertised when this attempt fails.
  if [ -e "$PWD/artifacts/runtime" ] || [ -L "$PWD/artifacts/runtime" ]; then
    [ ! -L "$PWD/artifacts/runtime" ] || return 1
    mv -- "$PWD/artifacts/runtime" "$_BK_BUNDLE_STATE/previous-runtime" || return 1
  fi
  git clone --no-checkout -- "$repo" "$BK_SOURCE_DIR" || return $?
  if [ -n "$expected" ]; then
    expected=$(bk_lower_hex "$expected")
    bk_validate_hex_length "$expected" 40 'source commit' || return 1
    resolved_ref="$expected"
    kind=commit
    git -C "$BK_SOURCE_DIR" cat-file -e "${expected}^{commit}" 2>/dev/null ||
      git -C "$BK_SOURCE_DIR" fetch origin "$expected" || return 1
    commit="$expected"
  else
    if git -C "$BK_SOURCE_DIR" show-ref --verify --quiet "refs/remotes/origin/$ref"; then
      resolved_ref="refs/remotes/origin/$ref"
    elif git -C "$BK_SOURCE_DIR" show-ref --verify --quiet "refs/tags/$ref"; then
      resolved_ref="refs/tags/$ref"
      kind=tag
    else
      kind=commit
    fi
    commit=$(git -C "$BK_SOURCE_DIR" rev-parse --verify --end-of-options "${resolved_ref}^{commit}") || return 1
  fi
  bk_validate_hex_length "$commit" 40 'resolved source commit' || return 1
  git -C "$BK_SOURCE_DIR" -c advice.detachedHead=false checkout --detach "$commit" || return $?
  state=$(git -C "$BK_SOURCE_DIR" status --porcelain) || return 1
  [ -z "$state" ] || return 1
  (
    cd "$_BK_BUNDLE_ROOT" || exit 1
    bk_write_source_info_env git "$repo" "$ref" "$commit" "" "" "" "" "" \
      "${expected:-$ref}" "$kind" "$commit"
  ) || return 1
  cp "$_BK_BUNDLE_RESULTS/source_info.env" "$_BK_BUNDLE_SOURCE_INFO" || return 1
  _bk_build_provenance
}

# The app supplies the applicability decision and command; the common layer records it.
bk_source_adjustment() {
  local _bk_id="$1" _bk_reason="$2" _bk_file="$3" _bk_before _bk_after _bk_diff
  local _bk_status=0 _bk_outcome=unchanged
  shift 3
  _bk_source_path "$_bk_file" || return 2
  [ "$PWD" = "$BK_SOURCE_DIR" ] && [ -f "$_bk_file" ] && [ ! -L "$_bk_file" ] || return 2
  _bk_before=$(bk_sha256_file "$_bk_file") || return 1
  "$@" || _bk_status=$?
  _bk_after=$(bk_sha256_file "$_bk_file") || return 1
  if [ "$_bk_status" -ne 0 ]; then _bk_outcome=failed; _BK_BUNDLE_FAILED=1
  elif [ "$_bk_before" != "$_bk_after" ]; then _bk_outcome=applied; fi
  _bk_diff=$(git diff --no-ext-diff --no-textconv --binary HEAD -- "$_bk_file") || return 1
  bk_json_object string id "$_bk_id" string reason "$_bk_reason" string file "$_bk_file" \
    string status "$_bk_outcome" json exit_code "$_bk_status" string before_sha256 "$_bk_before" \
    string after_sha256 "$_bk_after" \
    string source_diff "$_bk_diff" string source_diff_sha256 "$(_bk_bundle_text_sha256 "$_bk_diff")" \
    >> "$_BK_BUNDLE_STATE/adjustments"
  _bk_build_provenance || return 1
  return "$_bk_status"
}

# Capture each variant's configured source before compilation, not the last variant's tree.
bk_build_binary() {
  local _bk_label="$1" _bk_binary="$2" _bk_destination="$3" _bk_config _bk_configs="" _bk_separator=""
  local _bk_diff _bk_record _bk_status=0 _bk_hash="" _bk_mode="" _bk_config_hash _bk_content
  shift 3
  _bk_source_path "$_bk_binary" && _bk_bundle_path "$_bk_destination" || return 2
  [ "$PWD" = "$BK_SOURCE_DIR" ] || return 2
  while [ "${1:-}" = --config ]; do
    [ "$#" -ge 2 ] || return 2
    _bk_config="$2"; shift 2
    _bk_source_path "$_bk_config" || return 2
    [ -f "$_bk_config" ] && [ ! -L "$_bk_config" ] || return 2
    _bk_config_hash=$(bk_sha256_file "$_bk_config") || return 1
    _bk_content=$(cat -- "$_bk_config" && printf '.') || return 1
    _bk_record=$(bk_json_object string path "$_bk_config" string sha256 "$_bk_config_hash" \
      string content "${_bk_content%.}") || return 1
    _bk_configs+="${_bk_separator}${_bk_record}"; _bk_separator=,
  done
  [ "${1:-}" = -- ] && [ "$#" -ge 2 ] || return 2
  shift
  [ ! -e "$_BK_BUNDLE_STATE/payload/$_bk_destination" ] || return 2
  _bk_diff=$(git -C "$BK_SOURCE_DIR" diff --no-ext-diff --no-textconv --binary HEAD --) || return 1
  # Removing only this build's output prevents a successful no-op from publishing an old binary.
  [ ! -L "$_bk_binary" ] || return 2
  rm -f -- "$_bk_binary" || return 1
  "$@" || _bk_status=$?
  if [ "$_bk_status" -eq 0 ]; then
    if [ -f "$_bk_binary" ] && [ ! -L "$_bk_binary" ] && [ -x "$_bk_binary" ]; then
      _bk_hash=$(bk_sha256_file "$_bk_binary") || return 1
      _bk_mode=$(stat -c '%a' "$_bk_binary") || return 1
      mkdir -p "$_BK_BUNDLE_STATE/payload/$(dirname "$_bk_destination")" || return 1
      cp -p -- "$_bk_binary" "$_BK_BUNDLE_STATE/payload/$_bk_destination" || return 1
    else
      _bk_status=1
    fi
  fi
  _bk_record=$(bk_json_object string label "$_bk_label" string binary "$_bk_destination" \
    string binary_sha256 "$_bk_hash" string binary_mode "$_bk_mode" json exit_code "$_bk_status" \
    json configuration "[$_bk_configs]" string source_diff "$_bk_diff" \
    string source_diff_sha256 "$(_bk_bundle_text_sha256 "$_bk_diff")") || return 1
  printf '%s\n' "$_bk_record" >> "$_BK_BUNDLE_STATE/variants"
  [ "$_bk_status" -eq 0 ] || _BK_BUNDLE_FAILED=1
  _bk_build_provenance || return 1
  return "$_bk_status"
}

# Static inputs are explicit app-owned paths, preserving their relative layout.
_bk_publish_runtime() (
  set -euo pipefail
  local item path rel target files source_root="$BK_SOURCE_DIR"
  [ "$#" -gt 0 ]
  [ "$_BK_BUNDLE_FAILED" -eq 0 ]
  files=$(mktemp)
  trap 'rm -f "$files"' EXIT
  for item in "$@"; do
    _bk_bundle_path "$item"
    [ -e "$source_root/$item" ] && [ ! -L "$source_root/$item" ]
    case "$(realpath "$source_root/$item")" in "$source_root"/*) ;; *) exit 1 ;; esac
    find "$source_root/$item" -print0 > "$files"
    while IFS= read -r -d '' path; do
      rel="${path#"$source_root/"}"
      target="$_BK_BUNDLE_STATE/payload/$rel"
      [ ! -L "$path" ]
      if [ -d "$path" ]; then
        mkdir -p "$target"
      elif [ -f "$path" ]; then
        mkdir -p "$(dirname "$target")"
        if [ -e "$target" ]; then cmp -- "$path" "$target"
        else cp -p -- "$path" "$target"; fi
      else
        exit 1
      fi
    done < "$files"
  done
  _bk_build_provenance
  local package
  package=$(mktemp -d "$_BK_BUNDLE_ROOT/artifacts/.runtime.XXXXXXXX")
  cp -a "$_BK_BUNDLE_STATE/payload" "$package/payload"
  cp "$_BK_BUNDLE_SOURCE_INFO" "$package/source_info.env"
  cp "$_BK_BUNDLE_RESULTS/build_provenance.json" "$package/build.json"
  _bk_bundle_inventory "$package" > "$package/inventory"
  [ ! -e "$_BK_BUNDLE_ROOT/artifacts/runtime" ]
  mv -- "$package" "$_BK_BUNDLE_ROOT/artifacts/runtime"
)

bk_publish_runtime() {
  [ -s "$_BK_BUNDLE_STATE/variants" ] || return 1
  _bk_publish_runtime "$@"
}

# Interpreted applications carry tracked, adjusted source, not the Git database.
# Additional generated runtime files must be explicitly named by the caller.
bk_publish_source_runtime() (
  set -euo pipefail
  local files
  local paths=()
  files=$(mktemp)
  trap 'rm -f "$files"' EXIT
  git -C "$BK_SOURCE_DIR" ls-files -z > "$files"
  mapfile -d '' -t paths < "$files"
  [ "${#paths[@]}" -gt 0 ]
  _bk_publish_runtime "${paths[@]}" "$@"
)

# No fetch or checkout is permitted on the run path. Every execution gets a new copy.
bk_use_runtime() {
  local package="$PWD/artifacts/runtime" inventory work
  [ -d "$package" ] && [ ! -L "$package" ] && [ -f "$package/inventory" ] && [ ! -L "$package/inventory" ] || return 1
  inventory=$(mktemp) || return 1
  if ! _bk_bundle_inventory "$package" > "$inventory" || ! cmp -s "$inventory" "$package/inventory"; then
    rm -f "$inventory"
    echo 'runtime payload is incomplete or changed' >&2
    return 1
  fi
  rm -f "$inventory"
  [ -d "$package/payload" ] && [ -f "$package/source_info.env" ] && [ -f "$package/build.json" ] || return 1
  work=$(mktemp -d "$PWD/.runtime.XXXXXXXX") || return 1
  cp -a "$package/payload" "$work/payload" || return 1
  # Verify the copied bytes too, before handing them to the application.
  cp -p "$package/source_info.env" "$package/build.json" "$work/" || return 1
  inventory=$(mktemp) || return 1
  if ! _bk_bundle_inventory "$work" > "$inventory" || ! cmp -s "$inventory" "$package/inventory"; then
    rm -f "$inventory"
    return 1
  fi
  rm -f "$inventory"
  mkdir -p "${_BK_DEFAULT_RESULTS_DIR}" || return 1
  cp "$work/source_info.env" "${_BK_DEFAULT_RESULTS_DIR}/source_info.env" || return 1
  cp "$work/build.json" "${_BK_DEFAULT_RESULTS_DIR}/build_provenance.json" || return 1
  # Returned to the app for its normal cwd/input handling.
  # shellcheck disable=SC2034
  BK_RUNTIME_DIR="$work/payload"
}
