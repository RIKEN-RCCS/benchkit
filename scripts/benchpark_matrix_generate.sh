#!/bin/bash
set -euo pipefail

# BenchPark統合用のGitLab CI YAML生成スクリプト
# 既存のmatrix_generate.shとは独立して動作

BENCHPARK_LIST="config/benchpark-monitor/list.csv"
OUTPUT_FILE=".gitlab-ci.benchpark.yml"

source ./scripts/benchpark_functions.sh

SYSTEM_FILTER=""
APP_FILTER=""

while [[ $# -gt 0 ]]; do
  case $1 in
    system=*) SYSTEM_FILTER="${1#system=}" ;;
    app=*) APP_FILTER="${1#app=}" ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

echo "# Auto-generated BenchPark GitLab CI configuration" > "$OUTPUT_FILE"
echo "
stages:
  - benchpark_setup
  - benchpark_run
  - benchpark_results
" >> "$OUTPUT_FILE"

while IFS=, read -r system app description || [[ -n "$system" ]]; do
  # Trim whitespace
  system=$(echo "$system" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  app=$(echo "$app" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  description=$(echo "$description" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  
  [[ "$system" == "system" ]] && continue  # skip header
  [[ "$system" == *"#"* ]] && continue     # skip comments

  # Apply filters
  [[ -n "$SYSTEM_FILTER" ]] && {
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

  [[ -n "$APP_FILTER" ]] && {
    IFS=',' read -ra APP_LIST <<< "$APP_FILTER"
    app_match=false
    for filter_app in "${APP_LIST[@]}"; do
      if [[ "$app" == "$filter_app" ]]; then
        app_match=true
        break
      fi
    done
    [[ "$app_match" == false ]] && continue
  }

  job_prefix="benchpark_${system}_${app}"
  
  # Get system configuration
  build_run_tag=$(get_benchpark_system_tag "$system")
  
  if [[ -z "$build_run_tag" ]]; then
    echo "Warning: No tag found for system $system"
    continue
  fi

  echo "
${job_prefix}_setup:
  stage: benchpark_setup
  tags: [\"$build_run_tag\"]
  script:
    - echo \"Setting up BenchPark for $app on $system\"
    - bash scripts/benchpark_runner.sh setup $system $app
  artifacts:
    paths:
      - benchpark-workspace/
    expire_in: 1 week

${job_prefix}_run:
  stage: benchpark_run
  tags: [\"$build_run_tag\"]
  needs: [${job_prefix}_setup]
  script:
    - echo \"Running BenchPark experiment: $app on $system\"
    - bash scripts/benchpark_runner.sh run $system $app
    - echo \"Waiting for Ramble jobs to complete\"
    - bash scripts/benchpark_runner.sh wait $system $app
  artifacts:
    paths:
      - benchpark-workspace/
    expire_in: 1 week

${job_prefix}_results:
  stage: benchpark_results
  tags: [\"$build_run_tag\"]
  needs: [${job_prefix}_run]
  script:
    - echo \"Converting BenchPark results for $app on $system\"
    - python3 scripts/convert_benchpark_results.py $system $app
    - echo \"Results converted to BenchKit format\"
    - ls -la results/
  artifacts:
    paths:
      - results/
    expire_in: 1 week

" >> "$OUTPUT_FILE"

done < "$BENCHPARK_LIST"

echo "BenchPark GitLab CI configuration generated: $OUTPUT_FILE"