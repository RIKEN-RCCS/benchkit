#!/bin/bash
get_queue_template() {
    local system="$1"
	echo "[DEBUG] get_queue_template called for $system" >&2
    local queue_from_system
    local submit_cmd=""
    local template_raw=""
    local template=""

    queue_from_system=$(awk -F, -v s="$system" '$1==s && ($3=="run" || $3=="build_run") {print $4}' "$SYSTEM_FILE")
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


# CSV行をパースし、各フィールドを変数にエクスポートする（list.csv用）
# ヘッダー行（先頭が "system"）とコメント行（# を含む）はスキップ（return 1）
# 各フィールドの前後空白をトリムする
#
# 使用方法:
#   while IFS=, read -r f1 f2 f3 f4 f5 f6 f7; do
#     parse_list_csv_line "$f1" "$f2" "$f3" "$f4" "$f5" "$f6" "$f7" || continue
#     # $csv_system, $csv_mode, ... が使用可能
#   done < file.csv
parse_list_csv_line() {
    local system="$1" mode="$2" queue_group="$3" nodes="$4" numproc_node="$5" nthreads="$6" elapse="$7"
    system=$(echo "$system" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    mode=$(echo "$mode" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    queue_group=$(echo "$queue_group" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    nodes=$(echo "$nodes" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    numproc_node=$(echo "$numproc_node" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    nthreads=$(echo "$nthreads" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    elapse=$(echo "$elapse" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    [[ "$system" == "system" ]] && return 1
    [[ "$system" == *"#"* ]] && return 1

    export csv_system="$system" csv_mode="$mode" csv_queue_group="$queue_group"
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
