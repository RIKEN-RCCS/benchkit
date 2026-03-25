#!/bin/bash
get_queue_template() {
    local system="$1"
	echo "[DEBUG] get_queue_template called for $system" >&2
    local queue_from_system
    local submit_cmd=""
    local template_raw=""
    local template=""

    queue_from_system=$(awk -F, -v s="$system" '$1==s {print $5}' "$SYSTEM_FILE")
	echo "[DEBUG] system=$system -> queue_from_system=$queue_from_system" >&2

    if [[ -z "$queue_from_system" ]]; then
	    echo "[ERROR] queue not found for $system" >&2
		return 1
	fi

    while IFS=, read -r queue submit template_raw; do
        [[ -z "$queue" ]] && continue
        [[ "$queue" == \#* ]] && continue
        [[ "$queue" == "queue" ]] && continue

        if [[ "$queue_from_system" == "$queue" ]]; then
		    if [[ "$template_raw" == \"*\" ]]; then
              template="${template_raw%\"}"
              template="${template#\"}"
			else
              template="${template_raw}"
			fi
            echo "$submit $template"
            return 0
        fi
    done < "$QUEUE_FILE"
	 echo "[ERROR] No matching queue found for system=$system (queue=$queue_from_system)" >&2

    return 1
}

expand_template() {
    local template="$1"
	if command -v envsubst > /dev/null 2>&1; then
      echo "$template" | envsubst
    else
      echo "[WARN] envsubst not found; falling back to eval" >&2
      eval "echo \"$template\""
    fi
}

# System_CSVからmodeを取得する
# $1: システム名
# 存在しないシステム名の場合は空文字を返す（exit code 0）
get_system_mode() {
    local system="$1"
    awk -F, -v s="$system" '$1==s {print $2}' "$SYSTEM_FILE"
    return 0
}

# System_CSVからqueue_groupを取得する
# $1: システム名
# 存在しないシステム名の場合は空文字を返す（exit code 0）
get_system_queue_group() {
    local system="$1"
    awk -F, -v s="$system" '$1==s {print $6}' "$SYSTEM_FILE"
    return 0
}

# System_CSVからtag_buildを取得する
# $1: システム名
# mode=nativeの場合は空文字を返す（tag_buildカラム自体が空）
# 存在しないシステム名の場合は空文字を返す（exit code 0）
get_system_tag_build() {
    local system="$1"
    awk -F, -v s="$system" '$1==s {print $3}' "$SYSTEM_FILE"
    return 0
}

# System_CSVからtag_runを取得する
# $1: システム名
# 存在しないシステム名の場合は空文字を返す（exit code 0）
get_system_tag_run() {
    local system="$1"
    awk -F, -v s="$system" '$1==s {print $4}' "$SYSTEM_FILE"
    return 0
}

# CSV行をパースし、各フィールドを変数にエクスポートする（list.csv用）
# 6カラム形式: system,enable,nodes,numproc_node,nthreads,elapse
# ヘッダー行（先頭が "system"）はスキップ（return 1）
# enable=no → スキップ（return 1）
# enable が yes/no 以外 → stderr に警告出力しスキップ（return 1）
# 各フィールドの前後空白をトリムする
#
# 使用方法:
#   while IFS=, read -r f1 f2 f3 f4 f5 f6; do
#     parse_list_csv_line "$f1" "$f2" "$f3" "$f4" "$f5" "$f6" || continue
#     # $csv_system, $csv_enable, $csv_nodes, ... が使用可能
#   done < file.csv
parse_list_csv_line() {
    local system="$1" enable="$2" nodes="$3" numproc_node="$4" nthreads="$5" elapse="$6"
    system=$(echo "$system" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    enable=$(echo "$enable" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    nodes=$(echo "$nodes" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    numproc_node=$(echo "$numproc_node" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    nthreads=$(echo "$nthreads" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    elapse=$(echo "$elapse" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    [[ "$system" == "system" ]] && return 1

    if [[ "$enable" != "yes" && "$enable" != "no" ]]; then
        echo "Warning: invalid enable value '$enable' for system '$system', skipping" >&2
        return 1
    fi
    [[ "$enable" == "no" ]] && return 1

    export csv_system="$system" csv_enable="$enable"
    export csv_nodes="$nodes" csv_numproc_node="$numproc_node"
    export csv_nthreads="$nthreads" csv_elapse="$elapse"
    return 0
}

# CSV行をパースし、各フィールドを変数にエクスポートする（apps.csv用）
# ヘッダー行（先頭が "system"）とコメント行（# を含む）はスキップ（return 1）
# 各フィールドの前後空白をトリムする
#
# 使用方法:
#   while IFS=, read -r f1 f2 f3; do
#     parse_apps_csv_line "$f1" "$f2" "$f3" || continue
#     # $csv_system, $csv_app, $csv_description が使用可能
#   done < file.csv
parse_apps_csv_line() {
    local system="$1" app="$2" description="$3"
    system=$(echo "$system" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    app=$(echo "$app" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    description=$(echo "$description" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    [[ "$system" == "system" ]] && return 1
    [[ "$system" == *"#"* ]] && return 1

    export csv_system="$system" csv_app="$app" csv_description="$description"
    return 0
}

# カンマ区切りフィルタ文字列と対象値を受け取り、マッチ判定を返す
# フィルタ文字列が空の場合は常にマッチ（return 0）
# マッチした場合 return 0、マッチしない場合 return 1
#
# 使用方法:
#   match_filter "$SYSTEM_FILTER" "$system" || continue
#   match_filter "$CODE_FILTER" "$program" || continue
match_filter() {
    local filter_str="$1"
    local target="$2"

    [[ -z "$filter_str" ]] && return 0

    IFS=',' read -ra FILTER_LIST <<< "$filter_str"
    for filter_item in "${FILTER_LIST[@]}"; do
        if [[ "$target" == "$filter_item" ]]; then
            return 0
        fi
    done
    return 1
}

# send_results ジョブの YAML ブロックを生成
# $1: ジョブ名プレフィックス（例: qws_Fugaku_N1_P4_T12）
# $2: 依存ジョブ名（needs に指定するジョブ名）
# $3: 出力ファイル
emit_send_results_job() {
    local job_prefix="$1"
    local depends_on="$2"
    local output="$3"

    echo "
${job_prefix}_send_results:
  stage: send_results
  needs: [\"${depends_on}\"]
  tags: [fncx-curl-jq]
  environment:
    name: \$CI_COMMIT_BRANCH
  script:
    - bash scripts/send_results.sh

" >> "$output"
}

# artifacts ブロックを生成（YAML 文字列を返す）
# $1: パス（例: results/）
# $2: 有効期限（例: 1 week）
emit_artifacts_block() {
    local path="$1"
    local expire="$2"
    echo "  artifacts:
    paths:
      - ${path}
    expire_in: ${expire}"
}

# id_tokens ブロックを生成（YAML 文字列を返す）
emit_id_tokens_block() {
    echo "  id_tokens:
    CI_JOB_JWT:
      aud: https://gitlab.swc.r-ccs.riken.jp"
}

# ============================================================
# Estimate-related constants and functions
# ============================================================

# Estimate target systems (comma-separated)
ESTIMATE_SYSTEMS="MiyabiG,RC_GH200"

# Check if a system is an estimate target
# Returns 0 if the system is in ESTIMATE_SYSTEMS, 1 otherwise
# Usage: is_estimate_target "MiyabiG" && echo "target"
is_estimate_target() {
    local system="$1"
    IFS=',' read -ra EST_LIST <<< "$ESTIMATE_SYSTEMS"
    for item in "${EST_LIST[@]}"; do
        if [[ "$system" == "$item" ]]; then
            return 0
        fi
    done
    return 1
}

# Check if a program directory has an estimate script
# Returns 0 if $1/estimate.sh exists, 1 otherwise
# Usage: has_estimate_script "programs/qws" && echo "has estimate"
has_estimate_script() {
    local program_dir="$1"
    [[ -f "${program_dir}/estimate.sh" ]]
}

# Emit estimate job YAML block
# $1: job_prefix (e.g. qws_MiyabiG_N1_P4_T12)
# $2: depends_on (send_results job name, for ordering)
# $3: run_job_name (run/build_run job name, for artifacts)
# $4: code (program code name)
# $5: output_file
emit_estimate_job() {
    local job_prefix="$1"
    local depends_on="$2"
    local run_job="$3"
    local code="$4"
    local output="$5"

    echo "
${job_prefix}_estimate:
  stage: estimate
  needs: [\"${depends_on}\", \"${run_job}\"]
  tags: [fncx-curl-jq]
  environment:
    name: \$CI_COMMIT_BRANCH
  script:
    - echo \"Running estimation for ${code}\"
    - bash scripts/run_estimate.sh ${code}
  artifacts:
    paths:
      - results/
    expire_in: 1 week

" >> "$output"
}

# Emit send_estimate job YAML block
# $1: job_prefix (e.g. qws_MiyabiG_N1_P4_T12)
# $2: depends_on (estimate job name)
# $3: output_file
emit_send_estimate_job() {
    local job_prefix="$1"
    local depends_on="$2"
    local output="$3"

    echo "
${job_prefix}_send_estimate:
  stage: send_estimate
  needs: [\"${depends_on}\"]
  tags: [fncx-curl-jq]
  environment:
    name: \$CI_COMMIT_BRANCH
  script:
    - bash scripts/send_estimate.sh

" >> "$output"
}
