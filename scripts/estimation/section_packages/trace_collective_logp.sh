#!/bin/bash

bk_section_package_metadata_trace_collective_logp() {
  cat <<'EOF'
{"name":"trace_collective_logp","fallback_target":"interval_time_simple"}
EOF
}

bk_section_package_check_applicability_trace_collective_logp() {
  local item_json="$1"
  local item_kind="$2"
  local path
  local missing=()

  if [[ "$item_kind" != "section" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["item_kind:section_required"]}
EOF
    return 1
  fi

  if [[ "$(echo "$item_json" | jq -r '(.artifacts // []) | length')" == "0" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["section_artifact"]}
EOF
    return 1
  fi

  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if [[ ! -f "$path" ]]; then
      missing+=("\"artifact_path:${path}\"")
    fi
  done < <(echo "$item_json" | jq -r '(.artifacts // [])[]?.path')

  if (( ${#missing[@]} > 0 )); then
    printf '{"status":"not_applicable","missing_inputs":[%s]}\n' "$(IFS=,; echo "${missing[*]}")"
    return 1
  fi

  cat <<'EOF'
{"status":"applicable","missing_inputs":[]}
EOF
}

bk_section_package_transform_trace_collective_logp() {
  local item_json="$1"
  local target_nodes="$2"
  local bench_nodes="$3"
  local _default_factor="$4"
  local _item_kind="$5"
  local logp_factor

  logp_factor=$(awk -v target="$target_nodes" -v bench="$bench_nodes" '
    function safe_nodes(x) { return (x < 2 ? 2 : x) }
    function lg2(x) { return log(x) / log(2) }
    BEGIN {
      printf "%.12f", lg2(safe_nodes(target)) / lg2(safe_nodes(bench))
    }')

  echo "$item_json" | jq -c --argjson factor "$logp_factor" '
    .
    + {time: ((.time // .bench_time // 0) * $factor)}
    + {bench_time: (.bench_time // .time // 0)}
    + {scaling_method: "logP"}
  '
}
