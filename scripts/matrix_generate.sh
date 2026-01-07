#!/bin/bash
set -euo pipefail

# GitLab CI YAML Generation Rules:
# 1. Keep script sections simple - avoid complex shell constructs in YAML
# 2. Use basic commands only (echo, bash, ls)
# 3. Avoid conditional statements, pipes, or complex variable expansions in script arrays
# 4. For debugging, add simple echo statements rather than complex logic
# 5. If complex logic is needed, put it in separate shell scripts and call them

SYSTEM_FILE="system.csv"
QUEUE_FILE="queue.csv"
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
  - run
  - send_results
" >> "$OUTPUT_FILE"


for listfile in programs/*/list.csv; do
  program_dir=$(dirname "$listfile")
  program=$(basename "$program_dir")
 
  [[ -n "$CODE_FILTER" ]] && {
    # Support comma-separated code list
    IFS=',' read -ra CODE_LIST <<< "$CODE_FILTER"
    code_match=false
    for filter_code in "${CODE_LIST[@]}"; do
      if [[ "$program" == "$filter_code" ]]; then
        code_match=true
        break
      fi
    done
    [[ "$code_match" == false ]] && continue
  }

  while IFS=, read -r system mode queue_group nodes numproc_node nthreads elapse; do
    # Trim whitespace from all variables
    system=$(echo "$system" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    mode=$(echo "$mode" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    queue_group=$(echo "$queue_group" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    nodes=$(echo "$nodes" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    numproc_node=$(echo "$numproc_node" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    nthreads=$(echo "$nthreads" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    elapse=$(echo "$elapse" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    
    [[ "$system" == "system" ]] && continue  # skip header
    [[ "$system" == *"#"* ]] && continue  # skip #

    [[ -n "$SYSTEM_FILTER" ]] && {
      # Support comma-separated system list
      IFS=',' read -ra SYSTEM_LIST <<< "$SYSTEM_FILTER"
      system_match=false
      for filter_system in "${SYSTEM_LIST[@]}"; do
        if [[ "$system" == "$filter_system" ]]; then
          system_match=true
          break
        fi
      done
      [[ "$system_match" == false ]] && continue
    }

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
      
      echo "
${job_prefix}_build:
  stage: build
  tags: [\"$build_tag\"]
  script:
    - echo \"[BUILD] $program for $system\"
    - bash $program_path/build.sh $system
  artifacts:
    paths:
      - artifacts/
    expire_in: 1 week

${job_prefix}_run:
  stage: run
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp
  tags: [\"$run_tag\"]
  variables:
    SCHEDULER_PARAMETERS: \"${schedule_parameter}\"
  needs: [${job_prefix}_build]
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

${job_prefix}_send_results:
  stage: send_results
  needs: [\"${job_prefix}_run\"]
  tags: [fncx-curl-jq]
  environment:
    name: \$CI_COMMIT_BRANCH
  script:
    - bash scripts/send_results.sh

" >> "$OUTPUT_FILE"

    elif [[ "$mode" == "native" ]]; then
      build_run_tag=$(awk -F, -v s="$system" '$1==s && $3=="build_run" {print $2}' "$SYSTEM_FILE")

      # skip cases with empty tag
      if [[ -z "$build_run_tag" ]]; then
        echo "Skipping ${job_prefix}: build_run_tag is empty"
        continue
      fi
      
      echo "
${job_prefix}_build_run:
  stage: build
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

${job_prefix}_send_results:
  stage: send_results
  needs: [\"${job_prefix}_build_run\"]
  tags: [fncx-curl-jq]
  environment:
    name: \$CI_COMMIT_BRANCH
  script:
    - bash scripts/send_results.sh

" >> "$OUTPUT_FILE"

    else
      echo "Unknown mode: $mode"
      exit 1
    fi

  done < "$listfile"
done

