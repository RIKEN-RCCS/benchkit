#!/bin/bash
set -euo pipefail

# BenchPark統合用のGitLab CI YAML生成スクリプト
# 既存のmatrix_generate.shとは独立して動作

BENCHPARK_LIST="benchpark-bridge/config/apps.csv"
OUTPUT_FILE=".gitlab-ci.benchpark.yml"

source ./benchpark-bridge/scripts/common.sh
source ./scripts/job_functions.sh

# convert ジョブの YAML 定義を生成
# $1: ジョブ名プレフィックス, $2: ログインノードタグ, $3: 依存ジョブ名（空なら needs なし）
# $4: system, $5: app, $6: 出力ファイル
emit_convert_job() {
    local job_prefix="$1" login_tag="$2" depends_on="$3"
    local system="$4" app="$5" output="$6"

    local needs_line=""
    if [[ -n "$depends_on" ]]; then
        needs_line="
  needs: [\"${depends_on}\"]"
    fi

    echo "
${job_prefix}_convert:
  stage: benchpark_setup
  tags: [\"$login_tag\"]
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp${needs_line}
  script:
    - mkdir -p results
    - echo \"convert_started\" > results/convert.txt
    - echo \"Converting BenchPark results for $app on $system\"
    - python3 benchpark-bridge/scripts/result_converter.py $system $app
    - echo \"Results converted to BenchKit format\"
    - echo \"convert_completed\" >> results/convert.txt
    - ls -la results/
  artifacts:
    paths:
      - results/
    expire_in: 1 week
" >> "$output"
}

# send ジョブの YAML 定義を生成
# $1: ジョブ名プレフィックス, $2: 依存ジョブ名, $3: 出力ファイル
emit_send_job() {
    local job_prefix="$1" depends_on="$2" output="$3"

    echo "
${job_prefix}_send:
  stage: benchpark_setup
  tags: [fncx-curl-jq]
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp
  needs: [\"${depends_on}\"]
  script:
    - echo \"Checking CI variables\"
    - test -n \"\$RESULT_SERVER\" && echo \"RESULT_SERVER is set\" || echo \"RESULT_SERVER is NOT set\"
    - test -n \"\$RESULT_SERVER_KEY\" && echo \"RESULT_SERVER_KEY is set\" || echo \"RESULT_SERVER_KEY is NOT set\"
    - echo \"Sending results to server\"
    - bash scripts/send_results.sh

" >> "$output"
}

SYSTEM_FILTER=""
APP_FILTER=""
SEND_ONLY="false"

# コミットメッセージから[park-send]を検出
if [[ "${CI_COMMIT_MESSAGE:-}" =~ \[park-send\] ]]; then
  SEND_ONLY="true"
  echo "Detected [park-send] mode: result sending only"
fi

while [[ $# -gt 0 ]]; do
  case $1 in
    system=*) SYSTEM_FILTER="${1#system=}" ;;
    app=*) APP_FILTER="${1#app=}" ;;
    send_only=*) SEND_ONLY="${1#send_only=}" ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

echo "# Auto-generated BenchPark GitLab CI configuration" > "$OUTPUT_FILE"
echo "
stages:
  - benchpark_setup
" >> "$OUTPUT_FILE"

while IFS=, read -r system app description || [[ -n "$system" ]]; do
  parse_apps_csv_line "$system" "$app" "$description" || continue

  match_filter "$SYSTEM_FILTER" "$csv_system" || continue
  match_filter "$APP_FILTER" "$csv_app" || continue

  system="$csv_system"
  app="$csv_app"

  job_prefix="benchpark_${system}_${app}"
  # Replace problematic characters for YAML job names
  job_prefix=$(echo "$job_prefix" | sed 's/-/_/g')
  
  # Get system configuration
  # setupはJacamar-CIタグ、それ以外はログインノードタグ
  jacamar_tag=$(get_benchpark_system_tag "$system")
  login_tag=$(get_benchpark_login_tag "$system")
  
  if [[ -z "$jacamar_tag" ]] || [[ -z "$login_tag" ]]; then
    echo "Warning: No tag found for system $system"
    continue
  fi

  # Generate different job based on SEND_ONLY mode
  if [[ "$SEND_ONLY" == "true" ]]; then
    # Send-only mode: convert on login node, send on fncx-curl-jq
    emit_convert_job "$job_prefix" "$login_tag" "" "$system" "$app" "$OUTPUT_FILE"
    emit_send_job "$job_prefix" "${job_prefix}_convert" "$OUTPUT_FILE"
  else
    # Full mode: setup on Jacamar-CI, run on login node, convert on login node, send on fncx-curl-jq
    echo "
${job_prefix}_setup:
  stage: benchpark_setup
  tags: [\"$jacamar_tag\"]
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp
  script:
    - echo \"Setting up BenchPark for $app on $system\"
    - bash benchpark-bridge/scripts/runner.sh setup $app

${job_prefix}_run:
  stage: benchpark_setup
  tags: [\"$login_tag\"]
  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp
  needs: [\"${job_prefix}_setup\"]
  script:
    - mkdir -p results
    - echo \"run_started\" > results/run.txt
    - echo \"Running BenchPark experiment $app on $system\"
    - bash benchpark-bridge/scripts/runner.sh run $app
    - echo \"run_completed\" >> results/run.txt
    - ls -la results/
" >> "$OUTPUT_FILE"
    emit_convert_job "$job_prefix" "$login_tag" "${job_prefix}_run" "$system" "$app" "$OUTPUT_FILE"
    emit_send_job "$job_prefix" "${job_prefix}_convert" "$OUTPUT_FILE"
  fi

done < "$BENCHPARK_LIST"

echo "BenchPark GitLab CI configuration generated: $OUTPUT_FILE"