#!/bin/bash
set -euo pipefail

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
  - build_run
  - run
  - send_results
" >> "$OUTPUT_FILE"


for listfile in programs/*/list.csv; do
  program_dir=$(dirname "$listfile")
  program=$(basename "$program_dir")
 
  [[ -n "$CODE_FILTER" && "$program" != "$CODE_FILTER" ]] && continue

  while IFS=, read -r system mode queue_group nodes numproc_node nthreads elapse; do
    [[ "$system" == "system" ]] && continue  # skip header
    [[ "$system" == *"#"* ]] && continue  # skip #

    [[ -n "$SYSTEM_FILTER" && "$system" != "$SYSTEM_FILTER" ]] && continue

    job_prefix="${program}_${system}_N${nodes}_P${numproc_node}_T${nthreads}"
    program_path="$program_dir"

	export elapse nodes queue_group numproc_node nthreads 

	read -r submit_cmd template <<< "$(get_queue_template "$system")"
    if [[ -z "$submit_cmd" || -z "$template" ]]; then
       echo "Warning: No template for system $system"
       continue
     fi

	schedule_parameter=$(expand_template "$template")

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
  script:
    - echo \"[RUN] $program on $system\"
    - bash $program_path/run.sh $system $nodes ${numproc_node} ${nthreads}
    - bash scripts/result.sh $program $system
  artifacts:
    paths:
      - results/
    expire_in: 1 week

${job_prefix}_send_results:
  stage: send_results
  needs: [\"${job_prefix}_run\"]
  tags: [general]
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
  stage: build_run
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp
  tags: [\"$build_run_tag\"]
  variables:
    SCHEDULER_PARAMETERS: \"${schedule_parameter}\"
  script:
    - echo \"[BUILD_RUN:native] $program on $system\"
    - bash $program_path/build.sh $system
    - bash $program_path/run.sh $system $nodes ${numproc_node} ${nthreads}
    - bash scripts/result.sh $program $system
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

