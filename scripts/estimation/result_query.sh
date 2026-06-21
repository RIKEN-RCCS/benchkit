#!/bin/bash
# result_query.sh — Result Server query helpers for estimation.

# ---------------------------------------------------------------------------
# fetch_current_fom — Fetch baseline-system FOM from result_server API
#
# Arguments:
#   $1  system (e.g. Fugaku)
#   $2  code   (e.g. qws)
#   $3  exp    (optional, e.g. default)
#
# Requires: RESULT_SERVER, RESULT_SERVER_KEY environment variables
# Sets: est_current_fom (FOM value from the selected baseline-system result)
# Exits with 1 on failure.
# ---------------------------------------------------------------------------
fetch_current_fom() {
  local system="$1"
  local code="$2"
  local exp="${3:-}"

  local url="${RESULT_SERVER}/api/query/result?system=${system}&code=${code}"
  if [[ -n "$exp" ]]; then
    url="${url}&exp=${exp}"
  fi

  local response
  local curl_exit
  set +e
  response=$(bk_result_server_get_json "/api/query/result?system=${system}&code=${code}${exp:+&exp=${exp}}")
  curl_exit=$?
  set -e
  if [[ $curl_exit -ne 0 || -z "$response" ]]; then
    echo "ERROR: Failed to fetch baseline result for system=${system}, code=${code}, exp=${exp} (curl exit=$curl_exit)" >&2
    echo "ERROR: URL was: ${url}" >&2
    exit 1
  fi

  est_current_fom=$(echo "$response" | jq -r '.FOM')
  if [[ -z "$est_current_fom" || "$est_current_fom" == "null" ]]; then
    echo "ERROR: FOM not found in baseline result for system=${system}, code=${code}, exp=${exp}" >&2
    exit 1
  fi

  # Populate benchmark sub-object variables for current_system
  est_current_bench_system="$system"
  est_current_bench_fom="$est_current_fom"
  est_current_bench_nodes=$(echo "$response" | jq -r '.node_count // empty')
  est_current_bench_numproc_node=$(echo "$response" | jq -r '.numproc_node // empty')
  est_current_bench_timestamp=$(echo "$response" | jq -r '._meta.timestamp // empty')
  est_current_bench_uuid=$(echo "$response" | jq -r '._meta.uuid // empty')
  est_current_fom_breakdown=$(echo "$response" | jq -c '.fom_breakdown // empty')

  echo "Fetched baseline FOM for ${system}/${code}: ${est_current_fom}"
}
