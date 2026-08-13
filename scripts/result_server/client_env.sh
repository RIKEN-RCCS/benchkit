#!/bin/bash
# Shared validation for result-server clients.

bk_result_server_require_env() {
  if [[ -z "${RESULT_SERVER:-}" ]]; then
    echo "ERROR: RESULT_SERVER is not set" >&2
    exit 1
  fi
  if [[ "$RESULT_SERVER" != https://* ]]; then
    echo "ERROR: RESULT_SERVER must use https://" >&2
    exit 1
  fi
  if [[ "$RESULT_SERVER" =~ [[:space:]] ]]; then
    echo "ERROR: RESULT_SERVER must not contain whitespace" >&2
    exit 1
  fi
  if [[ -z "${RESULT_SERVER_CLIENT_CERT:-}" || -z "${RESULT_SERVER_CLIENT_KEY:-}" ]]; then
    echo "ERROR: RESULT_SERVER_CLIENT_CERT and RESULT_SERVER_CLIENT_KEY must be set" >&2
    exit 1
  fi
  if [[ ! -f "$RESULT_SERVER_CLIENT_CERT" || ! -r "$RESULT_SERVER_CLIENT_CERT" ]]; then
    echo "ERROR: RESULT_SERVER_CLIENT_CERT must be a readable file" >&2
    exit 1
  fi
  if [[ ! -f "$RESULT_SERVER_CLIENT_KEY" || ! -r "$RESULT_SERVER_CLIENT_KEY" ]]; then
    echo "ERROR: RESULT_SERVER_CLIENT_KEY must be a readable file" >&2
    exit 1
  fi
}

bk_result_server_set_curl_args() {
  curl_auth_args=(--cert "$RESULT_SERVER_CLIENT_CERT" --key "$RESULT_SERVER_CLIENT_KEY")
}
