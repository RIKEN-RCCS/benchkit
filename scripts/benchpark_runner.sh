#!/bin/bash
set -euo pipefail

# BenchPark実行管理スクリプト（システム既存インストール使用）

source ./scripts/benchpark_functions.sh

ACTION="$1"
SYSTEM="$2"
APP="$3"

WORKSPACE=$(get_benchpark_workspace "$SYSTEM" "$APP")
BENCHPARK_ROOT=$(get_benchpark_installation_path "$SYSTEM")

# BenchParkインストールの確認
if [[ -z "$BENCHPARK_ROOT" || ! -d "$BENCHPARK_ROOT" ]]; then
  echo "Error: BenchPark installation not found for system $SYSTEM"
  echo "Expected path: $BENCHPARK_ROOT"
  echo "Please ensure BenchPark is installed on the system or set BENCHPARK_ROOT environment variable"
  exit 1
fi

echo "Using BenchPark installation: $BENCHPARK_ROOT"

EXPERIMENT_PATH="$BENCHPARK_ROOT/experiments/${APP}/experiment.py"
SYSTEM_PATH=$(get_benchpark_system_path "$SYSTEM")

# システム設定パスをBenchParkインストール内に調整
if [[ "$SYSTEM_PATH" == benchpark/* ]]; then
  SYSTEM_PATH="$BENCHPARK_ROOT/${SYSTEM_PATH#benchpark/}"
fi

case "$ACTION" in
  "setup")
    echo "Setting up BenchPark workspace for $APP on $SYSTEM"
    
    # ワークスペースディレクトリを作成
    mkdir -p "$WORKSPACE"
    cd "$WORKSPACE"
    
    # BenchParkの初期化（既存インストールを使用）
    echo "Initializing BenchPark workspace using $BENCHPARK_ROOT"
    python3 "$BENCHPARK_ROOT/bin/benchpark" setup
    
    # 実験とシステム設定の確認
    echo "Configuring experiment and system"
    
    # 実験設定の確認
    if [[ ! -f "$EXPERIMENT_PATH" ]]; then
      echo "Error: Experiment file not found: $EXPERIMENT_PATH"
      exit 1
    fi
    
    # システム設定の確認
    if [[ ! -f "$SYSTEM_PATH" ]]; then
      echo "Error: System file not found: $SYSTEM_PATH"
      exit 1
    fi
    
    # BenchPark設定を生成
    echo "Generating BenchPark configuration"
    python3 "$BENCHPARK_ROOT/bin/benchpark" experiment "$APP" "$SYSTEM"
    
    echo "BenchPark setup completed"
    ;;
    
  "run")
    echo "Running BenchPark experiment: $APP on $SYSTEM"
    
    if [[ ! -d "$WORKSPACE" ]]; then
      echo "Error: Workspace not found: $WORKSPACE"
      exit 1
    fi
    
    cd "$WORKSPACE"
    
    # 既存のSpack/Ramble環境を使用
    echo "Building with Spack (using system installation)"
    spack install
    
    # Rambleで実験実行
    echo "Running experiment with Ramble (using system installation)"
    ramble workspace activate .
    ramble on
    
    echo "BenchPark experiment submitted"
    ;;
    
  "wait")
    echo "Waiting for BenchPark jobs to complete"
    
    if [[ ! -d "$WORKSPACE" ]]; then
      echo "Error: Workspace not found: $WORKSPACE"
      exit 1
    fi
    
    # Rambleジョブの完了を待機
    wait_for_ramble_jobs "$WORKSPACE"
    
    echo "BenchPark jobs completed"
    ;;
    
  *)
    echo "Usage: $0 {setup|run|wait} <system> <app>"
    echo "  setup: Initialize BenchPark workspace"
    echo "  run:   Execute BenchPark experiment"
    echo "  wait:  Wait for Ramble jobs to complete"
    echo ""
    echo "Environment variables:"
    echo "  BENCHPARK_ROOT: Override BenchPark installation path"
    exit 1
    ;;
esac