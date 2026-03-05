#!/bin/bash

# BenchPark統合用の共通関数

# システムに既存のBenchParkインストールパスを取得
get_benchpark_installation_path() {
  local system="$1"
  
  if [[ -n "$BENCHPARK_ROOT" ]]; then
    echo "$BENCHPARK_ROOT"
    elif command -v benchpark >/dev/null 2>&1; then
      dirname "$(dirname "$(which benchpark)")"
  else
    echo ""
  fi
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

# システムに対応するログインノード用GitLab Runnerタグを取得
# convert/sendなどログインノードで実行可能な処理用
get_benchpark_login_tag() {
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
  local job_ids="$2"
  local max_wait_time=3600  # 1時間
  local check_interval=60   # 1分間隔
  local elapsed=0
  
  echo "Waiting for Ramble jobs to complete in workspace: $workspace"
  
  cd "$workspace"
  
  # ジョブIDが指定されている場合は、そのジョブのみを監視
  if [[ -n "$job_ids" ]]; then
    echo "Monitoring specific job IDs: $job_ids"
    
    while [[ $elapsed -lt $max_wait_time ]]; do
      local all_completed=true
      
      for job_id in $job_ids; do
        # 特定のジョブIDの状態を確認
        if squeue -j "$job_id" 2>/dev/null | grep -q "$job_id"; then
          echo "Job $job_id still running (elapsed: ${elapsed}s)"
          all_completed=false
          break
        fi
      done
      
      if $all_completed; then
        echo "All specified jobs completed"
        return 0
      fi
      
      sleep $check_interval
      elapsed=$((elapsed + check_interval))
    done
  else
    # ジョブIDが取得できなかった場合は、ユーザーの全ジョブを監視（フォールバック）
    echo "Monitoring all user jobs (fallback mode)"
    
    while [[ $elapsed -lt $max_wait_time ]]; do
      local job_count=$(squeue -u "$USER" 2>/dev/null | wc -l)
      
      echo "Checking SLURM job status... (elapsed: ${elapsed}s, jobs: $((job_count - 1)))"
      
      if [[ $job_count -gt 1 ]]; then
        echo "Jobs still running, waiting..."
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
        continue
      fi
      
      echo "All jobs completed"
      return 0
    done
  fi
  
  echo "Timeout waiting for Ramble jobs to complete after ${max_wait_time}s"
  return 1
}

# BenchPark結果ディレクトリを取得
get_benchpark_results_dir() {
  local workspace="$1"
  echo "${workspace}/experiments/*/results"
}