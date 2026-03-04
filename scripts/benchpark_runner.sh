#!/bin/bash
set -euo pipefail

# BenchPark実行管理スクリプト（QC-GH200専用）

source ./scripts/benchpark_functions.sh

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
    
    # Rambleでジョブ投入
    echo "Submitting Ramble jobs from workspace: $RAMBLE_WORKSPACE"
    ramble --workspace-dir "$RAMBLE_WORKSPACE" on
    
    echo "BenchPark experiment submitted"
    ;;
    
  "wait")
    echo "Waiting for BenchPark jobs to complete"
    
    # SLURMのジョブ完了を待機
    wait_for_ramble_jobs "$BENCHPARK_ROOT/workspace/riken-cloud-gh200-nvhpc/${APP}/workspace"
    
    # ジョブ完了後、Rambleワークスペースを解析
    echo "Analyzing Ramble workspace results"
    RAMBLE_WORKSPACE="$BENCHPARK_ROOT/workspace/riken-cloud-gh200-nvhpc/${APP}/workspace"
    
    # setup.shで環境変数を設定
    . "$BENCHPARK_ROOT/workspace/setup.sh"
    
    # ワークスペースをアクティベート
    ramble workspace activate "$RAMBLE_WORKSPACE"
    
    # 結果を解析
    ramble workspace analyze
    
    echo "BenchPark jobs completed and analyzed"
    ;;
    
  *)
    echo "Usage: $0 {setup|run|wait} <app>"
    echo "  setup: Prepare BenchPark (QC-GH200)"
    echo "  run:   Submit BenchPark experiment (QC-GH200)"
    echo "  wait:  Wait for jobs to complete"
    exit 1
    ;;
esac
