#!/bin/bash
# Shared helpers for reading JSON from the result server.

set -euo pipefail

bk_result_server_require_env() {
  if [[ -z "${RESULT_SERVER:-}" ]]; then
    echo "ERROR: RESULT_SERVER is not set" >&2
    exit 1
  fi
  if [[ -z "${RESULT_SERVER_KEY:-}" ]]; then
    echo "ERROR: RESULT_SERVER_KEY is not set" >&2
    exit 1
  fi
}

bk_result_server_get_json() {
  local path_and_query="$1"
  bk_result_server_require_env
  curl --fail -L -sS -H "X-API-Key: ${RESULT_SERVER_KEY}" \
    "${RESULT_SERVER}${path_and_query}"
}

bk_result_server_get_json_to_file() {
  local path_and_query="$1"
  local output_path="$2"
  bk_result_server_require_env
  curl --fail -L -sS -H "X-API-Key: ${RESULT_SERVER_KEY}" \
    -o "$output_path" \
    "${RESULT_SERVER}${path_and_query}"
}
