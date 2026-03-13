#!/bin/bash
set -euo pipefail

# BenchPark実行管理スクリプト（QC-GH200専用）

source ./benchpark-bridge/scripts/common.sh

ACTION="$1"
APP="$2"

# QC-GH200固定
SYSTEM="qc-gh200"
BENCHPARK_ROOT="/home/users/nakamura/src/benchpark/r-ccs-fork/benchpark"

case "$ACTION" in
  "setup")
    echo "Setting up BenchPark for $APP on $SYSTEM"
    echo "Note: Setup is handled by BenchPark workspace initialization"
    ;;
    
  "run")
    echo "Running BenchPark experiment: $APP on $SYSTEM"
    
    # setup.shで環境変数を設定
    echo "Loading BenchPark environment"
    . "$BENCHPARK_ROOT/workspace/setup.sh"
    
    # Rambleワークスペースのパス
    RAMBLE_WORKSPACE="$BENCHPARK_ROOT/workspace/riken-cloud-gh200-nvhpc/${APP}/workspace"
    
    if [[ ! -d "$RAMBLE_WORKSPACE" ]]; then
      echo "Error: Ramble workspace not found: $RAMBLE_WORKSPACE"
      exit 1
    fi
    
    # Rambleでジョブ投入し、ジョブIDを取得
    echo "Submitting Ramble jobs from workspace: $RAMBLE_WORKSPACE"
    ramble_output=$(ramble --workspace-dir "$RAMBLE_WORKSPACE" on 2>&1)
    echo "$ramble_output"
    
    # SLURMジョブIDを抽出（例: "Submitted batch job 12345"）
    job_ids=$(echo "$ramble_output" | grep -oP 'Submitted batch job \K\d+' || true)
    
    if [[ -z "$job_ids" ]]; then
      echo "Warning: Could not extract SLURM job IDs from ramble output"
      echo "Falling back to user-based job monitoring"
      job_ids=""
    else
      echo "Extracted SLURM job IDs: $job_ids"
    fi
    
    echo "BenchPark experiment submitted"
    
    # ジョブ完了を待機（ジョブIDを渡す）
    echo "Waiting for BenchPark jobs to complete"
    wait_for_ramble_jobs "$RAMBLE_WORKSPACE" "$job_ids"
    
    # ジョブ完了後、Rambleワークスペースを解析
    echo "Analyzing Ramble workspace results"
    
    # ワークスペースをアクティベート
    ramble workspace activate "$RAMBLE_WORKSPACE"
    
    # 結果を解析
    ramble workspace analyze
    
    echo "BenchPark jobs completed and analyzed"
    ;;
    
  *)
    echo "Usage: $0 {setup|run} <app>"
    echo "  setup: Prepare BenchPark (QC-GH200)"
    echo "  run:   Submit BenchPark experiment and wait for completion (QC-GH200)"
    exit 1
    ;;
esac
