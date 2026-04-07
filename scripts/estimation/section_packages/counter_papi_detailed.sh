#!/bin/bash

bk_section_package_metadata_counter_papi_detailed() {
  cat <<'EOF'
{
  "name": "counter_papi_detailed",
  "fallback_target": "identity",
  "source_system_scope": {
    "kind": "benchmark_system",
    "accepted_values": ["any"]
  },
  "target_system_scope": {
    "accepted_values": ["any"]
  },
  "item_kind_scope": ["section"],
  "required_result_fields": ["name", "artifacts[].path", "time or bench_time"],
  "required_artifact_kinds": ["papi"],
  "acquisition_mode": "standard",
  "output_fields": ["time", "bench_time", "scaling_method"],
  "not_applicable_when": [
    "item kind is not section",
    "artifact list is empty",
    "artifact path is missing"
  ]
}
EOF
}

bk_section_package_check_applicability_counter_papi_detailed() {
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

bk_section_package_transform_counter_papi_detailed() {
  local item_json="$1"
  local _target_nodes="$2"
  local _bench_nodes="$3"
  local default_factor="$4"
  local _item_kind="$5"

  echo "$item_json" | jq -c --argjson factor "$default_factor" '
    .
    + {time: ((.time // .bench_time // 0) * $factor)}
    + {bench_time: (.bench_time // .time // 0)}
    + {scaling_method: "fixed-factor"}
  '
}
