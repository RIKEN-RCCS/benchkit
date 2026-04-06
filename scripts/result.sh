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

# Read source_info.env if it exists (written by bk_fetch_source in build stage)
source_info_block="null"
if [ -f results/source_info.env ]; then
  . results/source_info.env
  if [ "$BK_SOURCE_TYPE" = "git" ]; then
    source_info_block=$(cat <<EOFSI
{
    "source_type": "git",
    "repo_url": "$BK_REPO_URL",
    "branch": "$BK_BRANCH",
    "commit_hash": "$BK_COMMIT_HASH"
  }
EOFSI
)
  elif [ "$BK_SOURCE_TYPE" = "file" ]; then
    source_info_block=$(cat <<EOFSI
{
    "source_type": "file",
    "file_path": "$BK_FILE_PATH",
    "md5sum": "$BK_MD5SUM"
  }
EOFSI
)
  fi
fi

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
  "source_info": $source_info_block${fom_breakdown_block}${timing_block}${mode_block}${trigger_block}${build_job_block}${run_job_block}${pipeline_id_block}
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
