#!/bin/bash
# Shared helpers for reading JSON from the result server.

set -euo pipefail

bk_result_server_require_env() {
  if [[ -z "${RESULT_SERVER:-}" ]]; then
    echo "ERROR: RESULT_SERVER is not set" >&2
    exit 1
  fi
  if [[ -z "${RESULT_SERVER_CLIENT_CERT:-}" || -z "${RESULT_SERVER_CLIENT_KEY:-}" ]]; then
    echo "ERROR: RESULT_SERVER_CLIENT_CERT and RESULT_SERVER_CLIENT_KEY must be set" >&2
    exit 1
  fi
}

bk_result_server_set_curl_args() {
  curl_auth_args=(--cert "$RESULT_SERVER_CLIENT_CERT" --key "$RESULT_SERVER_CLIENT_KEY")
}

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
