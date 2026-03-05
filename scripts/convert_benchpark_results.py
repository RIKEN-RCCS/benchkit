#!/usr/bin/env python3
"""
BenchPark結果をBenchKit形式に変換するスクリプト

BenchParkのRamble結果をBenchKitのJSON形式に変換し、
既存の結果表示システムで表示できるようにします。
"""

import json
import os
import sys
import glob
import yaml
from datetime import datetime
from pathlib import Path


def find_benchpark_results(workspace_path, system, app):
    """BenchPark結果ファイルを検索"""
    # results.latest.txtを優先的に使用
    latest_results = os.path.join(workspace_path, "results.latest.txt")
    
    if os.path.exists(latest_results):
        print(f"Found latest results: {latest_results}")
        return [latest_results]
    
    # フォールバック: JSON形式の結果を検索
    results_pattern = f"{workspace_path}/experiments/*/results/*.json"
    result_files = glob.glob(results_pattern)
    
    if not result_files:
        print(f"No BenchPark results found in {workspace_path}")
        return []
    
    print(f"Found {len(result_files)} BenchPark result files")
    return result_files


def parse_benchpark_result(result_file):
    """BenchPark結果ファイルを解析"""
    # results.latest.txtの場合
    if result_file.endswith("results.latest.txt") or result_file.endswith(".txt"):
        return parse_ramble_results_txt(result_file)
    
    # JSON形式の場合
    try:
        with open(result_file, 'r') as f:
            data = json.load(f)
        
        # Ramble結果の基本構造を解析
        experiment_name = data.get('experiment', 'unknown')
        workload = data.get('workload', 'unknown')
        
        # パフォーマンス指標を抽出
        metrics = {}
        if 'results' in data:
            for key, value in data['results'].items():
                if isinstance(value, (int, float)):
                    metrics[key] = value
        
        # 実行時間を抽出
        execution_time = data.get('elapsed_time', 0)
        if isinstance(execution_time, str):
            # "HH:MM:SS" 形式の場合
            try:
                time_parts = execution_time.split(':')
                execution_time = int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + float(time_parts[2])
            except:
                execution_time = 0
        
        return {
            'experiment': experiment_name,
            'workload': workload,
            'metrics': metrics,
            'execution_time': execution_time,
            'raw_data': data
        }
        
    except Exception as e:
        print(f"Error parsing {result_file}: {e}")
        return None


def parse_ramble_results_txt(result_file):
    """Rambleの結果テキストファイルを解析（複数実験対応）
    
    results.latest.txtには複数の実験結果が含まれる可能性がある。
    各実験は "Experiment <name> figures of merit:" で始まる。
    """
    try:
        with open(result_file, 'r') as f:
            content = f.read()
        
        # 実験ごとに分割
        experiments = []
        current_experiment = None
        current_lines = []
        
        for line in content.split('\n'):
            # 新しい実験の開始
            if "Experiment " in line and "figures of merit:" in line:
                # 前の実験を保存
                if current_experiment:
                    experiments.append({
                        'name': current_experiment,
                        'lines': current_lines
                    })
                
                # 新しい実験を開始
                parts = line.split("Experiment ")
                if len(parts) > 1:
                    current_experiment = parts[1].split(" figures of merit:")[0]
                    current_lines = [line]
            elif current_experiment:
                current_lines.append(line)
        
        # 最後の実験を保存
        if current_experiment:
            experiments.append({
                'name': current_experiment,
                'lines': current_lines
            })
        
        # 各実験を解析
        parsed_experiments = []
        for exp in experiments:
            metrics = {}
            mpi_processes = 2  # デフォルト
            
            # MPI プロセス数を抽出（例: mpi_2 → 2）
            if "_mpi_" in exp['name']:
                try:
                    mpi_str = exp['name'].split("_mpi_")[-1]
                    mpi_processes = int(mpi_str)
                except:
                    pass
            
            # メトリクスを抽出
            for line in exp['lines']:
                # "Message Size:"で始まる行はコンテキスト名なのでスキップ
                if line.strip().startswith("Message Size:"):
                    continue
                
                if " = " in line:
                    try:
                        parts = line.split(" = ")
                        if len(parts) == 2:
                            key = parts[0].strip()
                            # "modifier::exit-code::"などの特殊なキーはスキップ
                            if "::" in key:
                                continue
                            
                            # 値から単位を削除
                            value_parts = parts[1].split()
                            if value_parts:
                                try:
                                    value = float(value_parts[0])
                                    metrics[key] = value
                                except ValueError:
                                    pass
                    except:
                        pass
            
            parsed_experiments.append({
                'experiment': exp['name'],
                'workload': exp['name'].split('.')[1] if '.' in exp['name'] else 'unknown',
                'metrics': metrics,
                'mpi_processes': mpi_processes,
                'execution_time': 0,
                'raw_data': {'lines': exp['lines']}
            })
        
        return parsed_experiments
        
    except Exception as e:
        print(f"Error parsing {result_file}: {e}")
        return []


def convert_to_benchkit_format(parsed_result, system, app):
    """BenchKit形式のJSONに変換（単一実験用）"""
    
    if not parsed_result:
        return None
    
    # 実験名からワークロード名を抽出
    experiment_name = parsed_result.get('experiment', 'unknown')
    workload = parsed_result.get('workload', 'unknown')
    mpi_processes = parsed_result.get('mpi_processes', 1)
    
    # メトリクスから代表的なFOM値を選択
    # TODO: 将来的にはベクトル的なFOM（メッセージサイズごとの値）に対応する必要がある
    metrics = parsed_result.get('metrics', {})
    fom_value = "0"
    fom_key = "unknown"
    
    if metrics:
        # 最初のメトリクスを代表値として使用
        fom_key = list(metrics.keys())[0]
        fom_value = str(metrics[fom_key])
    
    # BenchKit形式のJSON構造
    result = {
        "code": f"benchpark-{app}",
        "system": system,
        "FOM": fom_value,
        "FOM_version": experiment_name,
        "Exp": workload,
        "node_count": "1",
        "cpus_per_node": str(mpi_processes),
        "description": "dummy",
        "confidential": "null"
    }
    
    return result


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 convert_benchpark_results.py <system> <app>")
        sys.exit(1)
    
    system = sys.argv[1]
    app = sys.argv[2]
    
    # QC-GH200専用のワークスペースパス
    if system == "qc-gh200":
        workspace_path = f"/home/users/nakamura/src/benchpark/r-ccs-fork/benchpark/workspace/riken-cloud-gh200-nvhpc/{app}/workspace"
    else:
        # 他のシステムの場合
        workspace_path = f"benchpark-workspace/{system}/{app}"
    
    if not os.path.exists(workspace_path):
        print(f"Error: Workspace not found: {workspace_path}")
        sys.exit(1)
    
    print(f"Converting BenchPark results for {app} on {system}")
    print(f"Workspace path: {workspace_path}")
    
    # BenchPark結果を検索
    result_files = find_benchpark_results(workspace_path, system, app)
    
    if not result_files:
        print("No results to convert")
        sys.exit(1)
    
    # 結果を解析
    all_experiments = []
    for result_file in result_files:
        parsed = parse_benchpark_result(result_file)
        if parsed:
            # parse_benchpark_result()はリストを返す可能性がある（複数実験）
            if isinstance(parsed, list):
                all_experiments.extend(parsed)
            else:
                all_experiments.append(parsed)
    
    if not all_experiments:
        print("No valid results found")
        sys.exit(1)
    
    print(f"Found {len(all_experiments)} experiments")
    
    # 結果ディレクトリを作成
    os.makedirs("results", exist_ok=True)
    
    # 各実験を個別のJSONファイルとして保存
    output_files = []
    for i, experiment in enumerate(all_experiments):
        # BenchKit形式に変換
        benchkit_result = convert_to_benchkit_format(experiment, system, app)
        
        if not benchkit_result:
            print(f"Failed to convert experiment {i+1}")
            continue
        
        # BenchKit互換のファイル名形式（result*.json）
        # 既存のsend_results.shがそのまま使える
        # BenchKitはresult0.jsonから始まる
        output_file = f"results/result{i}.json"
        
        with open(output_file, 'w') as f:
            json.dump(benchkit_result, f, indent=2)
        
        output_files.append(output_file)
        print(f"Experiment {i+1}/{len(all_experiments)}: {experiment.get('experiment', 'unknown')}")
        print(f"  FOM: {benchkit_result['FOM']}")
        print(f"  Saved to: {output_file}")
    
    print(f"\nTotal: {len(output_files)} result files created")


if __name__ == "__main__":
    main()