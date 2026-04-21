#!/bin/bash
set -euo pipefail

# GitLab CI YAML Generation Rules:
# 1. Keep script sections simple - avoid complex shell constructs in YAML
# 2. Use basic commands only (echo, bash, ls)
# 3. Avoid conditional statements, pipes, or complex variable expansions in script arrays
# 4. For debugging, add simple echo statements rather than complex logic
# 5. If complex logic is needed, put it in separate shell scripts and call them

SYSTEM_FILE="config/system.csv"
QUEUE_FILE="config/queue.csv"
OUTPUT_FILE=".gitlab-ci.generated.yml"

source ./scripts/job_functions.sh

CODE_FILTER=""
SYSTEM_FILTER=""

while [[ $# -gt 0 ]]; do
  case $1 in
    code=*) CODE_FILTER="${1#code=}" ;;
    system=*) SYSTEM_FILTER="${1#system=}" ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done


echo "# Auto-generated GitLab CI configuration" > "$OUTPUT_FILE"
echo "
stages:
  - build
  - build_run
  - run
  - send_results
  - estimate
  - send_estimate

variables:
  PARENT_PIPELINE_SOURCE: \"$CI_PIPELINE_SOURCE\"
" >> "$OUTPUT_FILE"


# Track emitted build jobs to avoid duplicates (cross mode)
declare -A BUILT_MAP

for listfile in programs/*/list.csv; do
  program_dir=$(dirname "$listfile")
  program=$(basename "$program_dir")
 
  match_filter "$CODE_FILTER" "$program" || continue

  while IFS=, read -r system enable nodes numproc_node nthreads elapse; do
    parse_list_csv_line "$system" "$enable" "$nodes" "$numproc_node" "$nthreads" "$elapse" || continue

    match_filter "$SYSTEM_FILTER" "$csv_system" || continue

    system="$csv_system"
    nodes="$csv_nodes"
    numproc_node="$csv_numproc_node"
    nthreads="$csv_nthreads"
    elapse="$csv_elapse"

    mode=$(get_system_mode "$system")
    queue_group=$(get_system_queue_group "$system")

    # Skip if mode or queue_group is empty (system not found in System_CSV)
    if [[ -z "$mode" || -z "$queue_group" ]]; then
      echo "Warning: mode or queue_group not found for system $system, skipping"
      continue
    fi

    job_prefix="${program}_${system}_N${nodes}_P${numproc_node}_T${nthreads}"
    program_path="$program_dir"

    proc=$((nodes * numproc_node))
	export elapse nodes queue_group numproc_node nthreads proc

	read -r submit_cmd template <<< "$(get_queue_template "$system")"
    if [[ -z "$submit_cmd" || -z "$template" ]]; then
       echo "Warning: No template for system $system"
       continue
     fi

	schedule_parameter=$(expand_template "$template")
	# Escape special characters for YAML
	schedule_parameter=$(echo "$schedule_parameter" | sed 's/"/\\"/g')

    if [[ "$mode" == "cross" ]]; then
      build_tag=$(get_system_tag_build "$system")
      run_tag=$(get_system_tag_run "$system")

      # skip cases with empty tag
      if [[ -z "$build_tag" || -z "$run_tag" ]]; then
        echo "Skipping ${job_prefix}: build_tag or run_tag is empty"
        continue
      fi
      
      build_key="${program}_${system}"

      # Emit build job only once per code+system pair
      if [[ -z "${BUILT_MAP[$build_key]+_}" ]]; then
        echo "
${build_key}_build:
  stage: build
  tags: [\"$build_tag\"]
  script:
    - mkdir -p results
    - bash scripts/record_timestamp.sh results/build_start
    - echo \"[BUILD] $program for $system\"
    - bash $program_path/build.sh $system
    - bash scripts/record_timestamp.sh results/build_end
  artifacts:
    paths:
      - artifacts/
      - results/
    expire_in: 1 week
" >> "$OUTPUT_FILE"
        BUILT_MAP[$build_key]=1
      fi

      echo "
${job_prefix}_run:
  stage: run
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp
  tags: [\"$run_tag\"]
  variables:
    SCHEDULER_PARAMETERS: \"${schedule_parameter}\"
  needs: [${build_key}_build]
  before_script:
    - mkdir -p results
    - echo \"Pre-created results directory on login node\"
  script:
    - echo \"Starting job\"
    - ls -la $program_path/
    - bash scripts/record_timestamp.sh results/run_start
    - bash $program_path/run.sh $system $nodes ${numproc_node} ${nthreads}
    - bash scripts/record_timestamp.sh results/run_end
    - echo \"Job completed\"
    - ls -la .
  # after_script:
  #   - bash scripts/wait_for_nfs.sh results
  artifacts:
    paths:
      - results/
    expire_in: 1 week

" >> "$OUTPUT_FILE"

    emit_send_results_job "$job_prefix" "${job_prefix}_run" "$OUTPUT_FILE" "$program" "$system" "cross" "${build_key}_build" "${job_prefix}_run"

    if has_estimate_script "$program_path" && is_estimate_target "$system"; then
      emit_estimate_job "$job_prefix" "${job_prefix}_send_results" "${job_prefix}_run" "$program" "$OUTPUT_FILE"
      emit_send_estimate_job "$job_prefix" "${job_prefix}_estimate" "$OUTPUT_FILE"
    fi

    elif [[ "$mode" == "native" ]]; then
      build_run_tag=$(get_system_tag_run "$system")

      # skip cases with empty tag
      if [[ -z "$build_run_tag" ]]; then
        echo "Skipping ${job_prefix}: build_run_tag is empty"
        continue
      fi
      
      echo "
${job_prefix}_build_run:
  stage: build_run
  needs: []
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp
  tags: [\"$build_run_tag\"]
  variables:
    SCHEDULER_PARAMETERS: \"${schedule_parameter}\"
  before_script:
    - mkdir -p results
    - echo \"Pre-created results directory on login node\"
  script:
    - echo \"Starting build and run\"
    - bash scripts/record_timestamp.sh results/build_start
    - bash $program_path/build.sh $system
    - bash scripts/record_timestamp.sh results/build_end
    - bash scripts/record_timestamp.sh results/run_start
    - bash $program_path/run.sh $system $nodes ${numproc_node} ${nthreads}
    - bash scripts/record_timestamp.sh results/run_end
    - echo \"Job completed\"
    - ls -la .
  # after_script:
  #   - bash scripts/wait_for_nfs.sh results
  artifacts:
    paths:
      - results/
    expire_in: 1 week

" >> "$OUTPUT_FILE"

    emit_send_results_job "$job_prefix" "${job_prefix}_build_run" "$OUTPUT_FILE" "$program" "$system" "native" "${job_prefix}_build_run" "${job_prefix}_build_run"

    if has_estimate_script "$program_path" && is_estimate_target "$system"; then
      emit_estimate_job "$job_prefix" "${job_prefix}_send_results" "${job_prefix}_build_run" "$program" "$OUTPUT_FILE"
      emit_send_estimate_job "$job_prefix" "${job_prefix}_estimate" "$OUTPUT_FILE"
    fi

    else
      echo "Unknown mode: $mode"
      exit 1
    fi

  done < "$listfile"
done
