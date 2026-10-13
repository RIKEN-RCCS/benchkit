#!/bin/bash
# Shared helpers for reading JSON from the result server.

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/client_env.sh"

bk_result_server_get_json() {
  local path_and_query="$1"
  bk_result_server_require_env
  local curl_auth_args=()
  bk_result_server_set_curl_args
  curl --fail -L -sS "${curl_auth_args[@]}" \
    "${RESULT_SERVER}${path_and_query}"
}

bk_result_server_get_json_to_file() {
  local path_and_query="$1"
  local output_path="$2"
  bk_result_server_require_env
  local curl_auth_args=()
  bk_result_server_set_curl_args
  curl --fail -L -sS "${curl_auth_args[@]}" \
    -o "$output_path" \
    "${RESULT_SERVER}${path_and_query}"
}

bk_result_server_download_to_file() {
  local path_and_query="$1"
  local output_path="$2"
  bk_result_server_require_env
  local curl_auth_args=()
  bk_result_server_set_curl_args
  curl --fail -L -sS "${curl_auth_args[@]}" \
    -o "$output_path" \
    "${RESULT_SERVER}${path_and_query}"
}

# Return 3 only for a missing optional artifact. Authentication, transport,
# redirects, and server failures must not be mistaken for absent inputs.
bk_result_server_download_optional_to_file() {
  local path_and_query="$1" output_path="$2" status
  bk_result_server_require_env
  local curl_auth_args=()
  bk_result_server_set_curl_args
  if ! status=$(curl -sS "${curl_auth_args[@]}" --proto '=https' \
    --connect-timeout 30 --max-time 300 --max-filesize 1073741824 \
    -w '%{http_code}' -o "$output_path" "${RESULT_SERVER}${path_and_query}"); then
    rm -f "$output_path"
    return 1
  fi
  case "$status" in
    200) return 0 ;;
    404) rm -f "$output_path"; return 3 ;;
    *) rm -f "$output_path"; echo "ERROR: Artifact query returned HTTP ${status}" >&2; return 1 ;;
  esac
}
