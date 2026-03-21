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
" >> "$OUTPUT_FILE"


# Track emitted build jobs to avoid duplicates (cross mode)
declare -A BUILT_MAP

for listfile in programs/*/list.csv; do
  program_dir=$(dirname "$listfile")
  program=$(basename "$program_dir")
 
  match_filter "$CODE_FILTER" "$program" || continue

  while IFS=, read -r system mode queue_group nodes numproc_node nthreads elapse; do
    parse_list_csv_line "$system" "$mode" "$queue_group" "$nodes" "$numproc_node" "$nthreads" "$elapse" || continue

    match_filter "$SYSTEM_FILTER" "$csv_system" || continue

    system="$csv_system"
    mode="$csv_mode"
    queue_group="$csv_queue_group"
    nodes="$csv_nodes"
    numproc_node="$csv_numproc_node"
    nthreads="$csv_nthreads"
    elapse="$csv_elapse"

    job_prefix="${program}_${system}_N${nodes}_P${numproc_node}_T${nthreads}"
    program_path="$program_dir"

	export elapse nodes queue_group numproc_node nthreads 

	read -r submit_cmd template <<< "$(get_queue_template "$system")"
    if [[ -z "$submit_cmd" || -z "$template" ]]; then
       echo "Warning: No template for system $system"
       continue
     fi

	schedule_parameter=$(expand_template "$template")
	# Escape special characters for YAML
	schedule_parameter=$(echo "$schedule_parameter" | sed 's/"/\\"/g')

    if [[ "$mode" == "cross" ]]; then
      build_tag=$(awk -F, -v s="$system" '$1==s && $3=="build" {print $2}' "$SYSTEM_FILE")
      run_tag=$(awk -F, -v s="$system" '$1==s && $3=="run" {print $2}' "$SYSTEM_FILE")

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
    - echo \"[BUILD] $program for $system\"
    - bash $program_path/build.sh $system
  artifacts:
    paths:
      - artifacts/
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
    - bash $program_path/run.sh $system $nodes ${numproc_node} ${nthreads}
    - echo \"Job completed\"
    - ls -la .
    - bash scripts/result.sh $program $system
    - echo \"After result.sh execution\"
    - ls -la results/
    - echo \"Results directory contents count\"
    - ls results/ | wc -l
  after_script:
    - bash scripts/wait_for_nfs.sh results
  artifacts:
    paths:
      - results/
    expire_in: 1 week

" >> "$OUTPUT_FILE"

    emit_send_results_job "$job_prefix" "${job_prefix}_run" "$OUTPUT_FILE"

    if has_estimate_script "$program_path" && is_estimate_target "$system"; then
      emit_estimate_job "$job_prefix" "${job_prefix}_send_results" "${job_prefix}_run" "$program" "$OUTPUT_FILE"
      emit_send_estimate_job "$job_prefix" "${job_prefix}_estimate" "$OUTPUT_FILE"
    fi

    elif [[ "$mode" == "native" ]]; then
      build_run_tag=$(awk -F, -v s="$system" '$1==s && $3=="build_run" {print $2}' "$SYSTEM_FILE")

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
    - bash $program_path/build.sh $system
    - bash $program_path/run.sh $system $nodes ${numproc_node} ${nthreads}
    - echo \"Job completed\"
    - ls -la .
    - bash scripts/result.sh $program $system
    - echo \"After result.sh execution\"
    - ls -la results/
    - echo \"Results directory contents count\"
    - ls results/ | wc -l
  after_script:
    - bash scripts/wait_for_nfs.sh results
  artifacts:
    paths:
      - results/
    expire_in: 1 week

" >> "$OUTPUT_FILE"

    emit_send_results_job "$job_prefix" "${job_prefix}_build_run" "$OUTPUT_FILE"

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

