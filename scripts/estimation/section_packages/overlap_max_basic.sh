#!/bin/bash

bk_section_package_metadata_overlap_max_basic() {
  cat <<'EOF'
{"name":"overlap_max_basic","fallback_target":null}
EOF
}

bk_section_package_check_applicability_overlap_max_basic() {
  local item_json="$1"
  local item_kind="$2"
  local path
  local missing=()

  if [[ "$item_kind" != "overlap" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["item_kind:overlap_required"]}
EOF
    return 1
  fi

  if [[ "$(echo "$item_json" | jq -r '(.artifacts // []) | length')" == "0" ]]; then
    cat <<'EOF'
{"status":"not_applicable","missing_inputs":["overlap_artifact"]}
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

bk_section_package_transform_overlap_max_basic() {
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
