#!/bin/bash
#set -euo pipefail

if [ ! -d results ] || [ ! -f results/result ]; then
  echo "Error: results/ or results/result not found"
  exit 1
fi

if ! grep -q "FOM" results/result; then
  echo "Error: results/result does not contain FOM"
  exit 1
fi

ls results/
cat results/result

code=$1
system=$2
execution_mode=$3
build_job=$4
run_job=$5
pipeline_id=$6
node_count='how_many'
numproc_node=""
nthreads=""

# Read the lightweight profiler manifest from a padata archive and turn it into
# the small profile_data block stored in result*.json. Missing or unreadable
# archives are ignored so FOM result generation is not blocked by profiler
# postprocessing problems.
build_profile_data_summary() {
  local tgz_file="$1"

  if [[ ! -f "$tgz_file" ]]; then
    printf '%s' ""
    return 0
  fi

  local meta_member
  meta_member=$(tar -tzf "$tgz_file" 2>/dev/null | grep 'meta\.json$' | head -n 1 || true)
  if [[ -z "$meta_member" ]]; then
    printf '%s' ""
    return 0
  fi

  local meta_json
  meta_json=$(tar -xOf "$tgz_file" "$meta_member" 2>/dev/null || true)
  if [[ -z "$meta_json" ]]; then
    printf '%s' ""
    return 0
  fi

  echo "$meta_json" | jq -c '
    {
      tool: .tool,
      level: .level,
      report_format: .report_format,
      raw_dir: .raw_dir,
      run_count: ((.runs // []) | length),
      events: (
        if .tool == "fapp"
        then ((.runs // []) | map(.event) | map(select(. != null and . != "")))
        else []
        end
      ),
      ncu_options: (
        if .tool == "ncu" and ((.measurement.ncu_options // null) | type) == "array"
        then .measurement.ncu_options
        else []
        end
      ),
      report_kinds: ((.runs // []) | map(.reports // []) | add | map(.kind) | unique)
    }
  ' 2>/dev/null || true
}

decode_base64_value() {
  if base64 --decode >/dev/null 2>&1 </dev/null; then
    base64 --decode
    return $?
  fi
  if base64 -d >/dev/null 2>&1 </dev/null; then
    base64 -d
    return $?
  fi
  if base64 -D >/dev/null 2>&1 </dev/null; then
    base64 -D
    return $?
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl base64 -d -A
    return $?
  fi
  return 1
}

source_info_env_value() {
  local key="$1"
  local line
  line=$(awk -F= -v k="${key}_B64" '$1 == k {print substr($0, length(k) + 2); exit}' results/source_info.env)
  if [ -n "$line" ]; then
    printf '%s' "$line" | decode_base64_value 2>/dev/null || true
    return 0
  fi

  # Legacy fallback for old source_info.env files. Treat the file as data and
  # accept only simple quoted values; never source it as shell.
  awk -v key="$key" '
    index($0, "export " key "=\"") == 1 && substr($0, length($0), 1) == "\"" {
      prefix = "export " key "=\""
      value = substr($0, length(prefix) + 1, length($0) - length(prefix) - 1)
      if (value !~ /[`$\\]/) {
        print value
      }
      exit
    }
  ' results/source_info.env
}

build_source_info_block() {
  if [ ! -f results/source_info.env ]; then
    printf '%s' "null"
    return 0
  fi

  local source_type
  source_type=$(source_info_env_value BK_SOURCE_TYPE)

  if [ "$source_type" = "git" ]; then
    jq -n \
      --arg source_type "git" \
      --arg repo_url "$(source_info_env_value BK_REPO_URL)" \
      --arg branch "$(source_info_env_value BK_BRANCH)" \
      --arg commit_hash "$(source_info_env_value BK_COMMIT_HASH)" \
      '{source_type: $source_type, repo_url: $repo_url, branch: $branch, commit_hash: $commit_hash}'
    return 0
  fi

  if [ "$source_type" = "file" ]; then
    jq -n \
      --arg source_type "file" \
      --arg file_path "$(source_info_env_value BK_FILE_PATH)" \
      --arg md5sum "$(source_info_env_value BK_MD5SUM)" \
      '{source_type: $source_type, file_path: $file_path, md5sum: $md5sum}'
    return 0
  fi

  printf '%s' "null"
}

# Read source_info.env if it exists (written by bk_fetch_source in build stage).
# It is parsed as data and converted with jq; it is never sourced as shell.
source_info_block=$(build_source_info_block)

# Function to write a Result_JSON file for one FOM block
# Arguments: $1=index, uses global vars: code, system, fom, fom_version, exp, node_count, numproc_node, description, confidential, sections_json, overlaps_json
write_result_json() {
  local idx="$1"
  local fom_breakdown_block=""

  # Build pipeline_timing block if timing.env exists (only for first result to avoid duplication)
  local timing_block=""
  if [ "$idx" = "0" ] && [ -f results/timing.env ]; then
    source results/timing.env
    timing_block=",
  \"pipeline_timing\": {
    \"build_time\": ${BUILD_TIME:-0},
    \"queue_time\": ${QUEUE_TIME:-0},
    \"run_time\": ${RUN_TIME:-0}
  }"
  fi

  # Build execution_mode block
  local mode_block=""
  if [ -n "$execution_mode" ]; then
    mode_block=",
  \"execution_mode\": \"$execution_mode\""
  fi

  # Build ci_trigger block (use PARENT_PIPELINE_SOURCE from parent pipeline)
  local trigger_val="${PARENT_PIPELINE_SOURCE:-${CI_PIPELINE_SOURCE:-unknown}}"
  local trigger_block=",
  \"ci_trigger\": \"$trigger_val\""

  # Build job identifier blocks
  local build_job_block=""
  if [ -n "$build_job" ]; then
    build_job_block=",
  \"build_job\": \"$build_job\""
  fi

  local run_job_block=""
  if [ -n "$run_job" ]; then
    run_job_block=",
  \"run_job\": \"$run_job\""
  fi

  local pipeline_id_block=""
  if [ -n "$pipeline_id" ]; then
    pipeline_id_block=",
  \"pipeline_id\": $pipeline_id"
  fi

  # Attach the profiler summary that matches this FOM index. fapp exposes
  # counter events, while ncu exposes the Nsight Compute option preset.
  local profile_data_block=""
  local profile_data_summary=""
  profile_data_summary=$(build_profile_data_summary "results/padata${idx}.tgz")
  if [ -n "$profile_data_summary" ]; then
    profile_data_block=",
  \"profile_data\": ${profile_data_summary}"
  fi

  # Build fom_breakdown if sections exist
  if [ -n "$sections_json" ]; then
    # Validate overlap section names
    if [ -n "$overlaps_json" ]; then
      local overlap_count
      overlap_count=$(echo "$overlaps_json" | jq 'length')
      for (( oi=0; oi<overlap_count; oi++ )); do
        local overlap_sections
        overlap_sections=$(echo "$overlaps_json" | jq -r ".[$oi].sections[]")
        while IFS= read -r osec; do
          if ! echo "$sections_json" | jq -e ".[] | select(.name == \"$osec\")" > /dev/null 2>&1; then
            echo "ERROR: OVERLAP references undefined section: $osec" >&2
          fi
        done <<< "$overlap_sections"
      done
    fi

    local overlaps_part="[]"
    if [ -n "$overlaps_json" ]; then
      overlaps_part="$overlaps_json"
    fi
    fom_breakdown_block=",
  \"fom_breakdown\": {
    \"sections\": ${sections_json},
    \"overlaps\": ${overlaps_part}
  }"
  fi

  cat <<EOF > results/result${idx}.json
{
  "code": "$code",
  "system": "$system",
  "FOM": "$fom",
  "FOM_version": "$fom_version",
  "Exp": "$exp",
  "node_count": "$node_count",
  "numproc_node": "$numproc_node",
  "nthreads": "$nthreads",
  "description": "$description",
  "confidential": "$confidential",
  "source_info": $source_info_block${profile_data_block}${fom_breakdown_block}${timing_block}${mode_block}${trigger_block}${build_job_block}${run_job_block}${pipeline_id_block}
}
EOF

  # Ensure file is completely written and synced
  sync
  sleep 2

  # Verify file integrity locally
  if [[ -s "results/result${idx}.json" ]] && jq . "results/result${idx}.json" >/dev/null 2>&1; then
    echo "results/result${idx}.json created and verified locally."
  else
    echo "WARNING: results/result${idx}.json may be incomplete, retrying..."
    sleep 5
    sync
    if [[ ! -s "results/result${idx}.json" ]]; then
      echo "ERROR: Failed to create valid results/result${idx}.json"
    fi
  fi
}

i=0
in_fom_block=false
fom=""
fom_version="null"
exp="null"
description="null"
confidential="null"
sections_json=""
overlaps_json=""

while IFS= read -r line; do
  if [[ "$line" == *FOM:* ]]; then
    # If we were already in a FOM block, write the previous one
    if [ "$in_fom_block" = true ]; then
      write_result_json "$i"
      i=$(expr $i + 1)
    fi

    in_fom_block=true
    sections_json=""
    overlaps_json=""

    # Parse FOM line (existing logic)
    fom=$(echo $line | grep -Eo 'FOM:[ ]*[0-9.]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    if [ -z "$fom" ]; then
      fom=null
    fi

    node_count_line=$(echo $line | grep -Eo 'node_count:[ ]*[0-9]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    if [ -n "$node_count_line" ]; then
      node_count=${node_count_line}
    fi

    numproc_node_line=$(echo $line | grep -Eo 'numproc_node:[ ]*[0-9]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    if [ -n "$numproc_node_line" ]; then
      numproc_node=${numproc_node_line}
    else
      numproc_node=""
    fi

    nthreads_line=$(echo $line | grep -Eo 'nthreads:[ ]*[0-9]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    if [ -n "$nthreads_line" ]; then
      nthreads=${nthreads_line}
    else
      nthreads=""
    fi

    if echo "$line" | grep -q 'Exp:'; then
      exp=$(echo "$line" | grep -Eo 'Exp:[ ]*[a-zA-Z0-9_.-]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    else
      exp=null
    fi

    if echo "$line" | grep -q 'FOM_version:'; then
      echo $line
      fom_version=$(echo "$line" | grep -Eo 'FOM_version:[ ]*[a-zA-Z0-9_.-]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    else
      fom_version=null
    fi

    if echo "$line" | grep -q 'description:'; then
      description=$(echo "$line" | grep -Eo 'description:[ ]*[a-zA-Z0-9_.-]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    else
      description=null
    fi

    if echo "$line" | grep -q 'confidential:'; then
      confidential=$(echo "$line" | grep -Eo 'confidential:[ ]*[a-zA-Z0-9_.-]*' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    else
      confidential=null
    fi

  elif [[ "$line" == SECTION:* ]]; then
    # Parse SECTION line:
    # SECTION:name time:seconds [type:value] [members:a,b] [estimation_package:package_name] [artifact:path]
    sec_name=$(echo "$line" | sed 's/^SECTION://' | awk '{print $1}')
    sec_time=$(echo "$line" | grep -Eo 'time:[ ]*[^ ]+' | awk -F':' '{print $2}' | sed 's/^ *//')
    sec_type=$(echo "$line" | grep -Eo 'type:[ ]*[^ ]+' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    sec_members=$(echo "$line" | grep -Eo 'members:[ ]*[^ ]+' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    sec_package=$(echo "$line" | grep -Eo 'estimation_package:[ ]*[^ ]+' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    sec_artifact=$(echo "$line" | grep -Eo 'artifact:[ ]*[^ ]+' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')

    if [ "$sec_type" = "overlap" ]; then
      if [ -z "$sec_members" ]; then
        sec_members="$sec_name"
      fi
      sec_members_array=$(echo "$sec_members" | tr ',' '\n' | jq -R . | jq -s .)
      sec_entry=$(jq -cn \
        --argjson sections "$sec_members_array" \
        --argjson time "$sec_time" \
        --arg estimation_package "$sec_package" \
        --arg artifact "$sec_artifact" '
          {
            sections: $sections,
            time: $time
          }
          + (if $estimation_package != "" then {estimation_package: $estimation_package} else {} end)
          + (if $artifact != "" then {artifacts: [{type: "file_reference", path: $artifact}]} else {} end)
        ')

      if [ -z "$overlaps_json" ]; then
        overlaps_json="[${sec_entry}]"
      else
        overlaps_json=$(echo "$overlaps_json" | jq ". + [${sec_entry}]")
      fi
    else
      sec_entry=$(jq -cn \
        --arg name "$sec_name" \
        --argjson time "$sec_time" \
        --arg estimation_package "$sec_package" \
        --arg artifact "$sec_artifact" '
          {
            name: $name,
            time: $time
          }
          + (if $estimation_package != "" then {estimation_package: $estimation_package} else {} end)
          + (if $artifact != "" then {artifacts: [{type: "file_reference", path: $artifact}]} else {} end)
        ')

      if [ -z "$sections_json" ]; then
        sections_json="[${sec_entry}]"
      else
        sections_json=$(echo "$sections_json" | jq ". + [${sec_entry}]")
      fi
    fi

  elif [[ "$line" == OVERLAP:* ]]; then
    # Parse OVERLAP line:
    # OVERLAP:sectionA,sectionB time:seconds [estimation_package:package_name] [artifact:path]
    ovl_sections_str=$(echo "$line" | sed 's/^OVERLAP://' | awk '{print $1}')
    ovl_time=$(echo "$line" | grep -Eo 'time:[ ]*[^ ]+' | awk -F':' '{print $2}' | sed 's/^ *//')
    ovl_package=$(echo "$line" | grep -Eo 'estimation_package:[ ]*[^ ]+' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')
    ovl_artifact=$(echo "$line" | grep -Eo 'artifact:[ ]*[^ ]+' | head -n1 | awk -F':' '{print $2}' | sed 's/^ *//')

    # Convert comma-separated section names to JSON array
    ovl_sections_array=$(echo "$ovl_sections_str" | tr ',' '\n' | jq -R . | jq -s .)

    ovl_entry=$(jq -cn \
      --argjson sections "$ovl_sections_array" \
      --argjson time "$ovl_time" \
      --arg estimation_package "$ovl_package" \
      --arg artifact "$ovl_artifact" '
        {
          sections: $sections,
          time: $time
        }
        + (if $estimation_package != "" then {estimation_package: $estimation_package} else {} end)
        + (if $artifact != "" then {artifacts: [{type: "file_reference", path: $artifact}]} else {} end)
      ')

    if [ -z "$overlaps_json" ]; then
      overlaps_json="[${ovl_entry}]"
    else
      overlaps_json=$(echo "$overlaps_json" | jq ". + [${ovl_entry}]")
    fi
  fi

done < results/result

# Write the last FOM block
if [ "$in_fom_block" = true ]; then
  write_result_json "$i"
  i=$(expr $i + 1)
fi

# Create completion marker after all JSON files are created
echo "All result JSON files created at $(date)" > results/.complete
sync
sleep 5
echo "Result processing completed. Created $i JSON files."
