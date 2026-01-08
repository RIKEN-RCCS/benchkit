#!/bin/bash

# BenchPark統合用の共通関数

# システムに既存のBenchParkインストールパスを取得
get_benchpark_installation_path() {
  local system="$1"
  
  case "$system" in
    "fugaku")
      echo "/vol0004/apps/benchpark"  # Fugakuの既存BenchParkパス
      ;;
    "qc-gh200")
      echo "/lvs0/rccs-nghpcadu/nakamura/benchkit_monitoring/benchpark"  # QC-GH200の既存BenchParkパス
      ;;
    *)
      # デフォルトは環境変数またはPATHから検索
      if [[ -n "$BENCHPARK_ROOT" ]]; then
        echo "$BENCHPARK_ROOT"
      elif command -v benchpark >/dev/null 2>&1; then
        dirname "$(dirname "$(which benchpark)")"
      else
        echo ""
      fi
      ;;
  esac
}

# システムに対応するGitLab Runnerタグを取得
get_benchpark_system_tag() {
  local system="$1"
  local tag=""
  
  case "$system" in
    "fugaku")
      tag="fugaku_login1"
      ;;
    "qc-gh200")
      tag="rccs_cloud_login"
      ;;
    *)
      echo "Unknown system: $system" >&2
      return 1
      ;;
  esac
  
  echo "$tag"
}

# BenchParkワークスペースのパスを取得
get_benchpark_workspace() {
  local system="$1"
  local app="$2"
  echo "benchpark-workspace/${system}/${app}"
}

# BenchPark実験設定ファイルのパスを取得（システム既存インストール用）
get_benchpark_experiment_path() {
  local system="$1"
  local app="$2"
  local benchpark_root=$(get_benchpark_installation_path "$system")
  echo "$benchpark_root/experiments/${app}/experiment.py"
}

# BenchParkシステム設定ファイルのパスを取得（相対パス）
get_benchpark_system_path() {
  local system="$1"
  
  case "$system" in
    "fugaku")
      echo "systems/riken-fugaku/system.py"
      ;;
    "qc-gh200")
      echo "systems/qc-gh200/system.py"
      ;;
    *)
      echo "systems/${system}/system.py"
      ;;
  esac
}

# Rambleジョブの完了を待機
wait_for_ramble_jobs() {
  local workspace="$1"
  local max_wait_time=3600  # 1時間
  local check_interval=60   # 1分間隔
  local elapsed=0
  
  echo "Waiting for Ramble jobs to complete in workspace: $workspace"
  
  while [[ $elapsed -lt $max_wait_time ]]; do
    # Rambleワークスペースでジョブ状態を確認
    cd "$workspace"
    
    # ramble workspace statusでジョブ状態を確認
    if ramble workspace status | grep -q "No active experiments"; then
      echo "All Ramble jobs completed"
      return 0
    fi
    
    # 実行中のジョブがあるかチェック
    if ramble workspace status | grep -q "RUNNING\|QUEUED"; then
      echo "Jobs still running, waiting..."
      sleep $check_interval
      elapsed=$((elapsed + check_interval))
    else
      echo "All jobs completed or failed"
      return 0
    fi
  done
  
  echo "Timeout waiting for Ramble jobs to complete"
  return 1
}

# BenchPark結果ディレクトリを取得
get_benchpark_results_dir() {
  local workspace="$1"
  echo "${workspace}/experiments/*/results"
}