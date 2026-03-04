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
    """Rambleの結果テキストファイルを解析"""
    try:
        with open(result_file, 'r') as f:
            content = f.read()
        
        # 簡易的な解析: 最初の実験名とメトリクスを抽出
        lines = content.split('\n')
        
        experiment_name = "unknown"
        metrics = {}
        
        # 最初の実験名を抽出
        for line in lines:
            if "Experiment " in line and "figures of merit:" in line:
                # "Experiment osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2 figures of merit:"
                parts = line.split("Experiment ")
                if len(parts) > 1:
                    experiment_name = parts[1].split(" figures of merit:")[0]
                break
        
        # メトリクスを抽出（数値のみ）
        for line in lines:
            # "Bandwidth = 6.50 MB/s" のようなパターンを抽出
            if " = " in line and ("MB/s" in line or "us" in line or "Latency" in line or "Bandwidth" in line):
                try:
                    parts = line.split(" = ")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        # 値から単位を削除
                        value_str = parts[1].split()[0]
                        try:
                            value = float(value_str)
                            metrics[key] = value
                        except ValueError:
                            pass
                except:
                    pass
        
        return {
            'experiment': experiment_name,
            'workload': 'unknown',
            'metrics': metrics,
            'execution_time': 0,
            'raw_data': {'content': content}
        }
        
    except Exception as e:
        print(f"Error parsing {result_file}: {e}")
        return None


def convert_to_benchkit_format(parsed_results, system, app):
    """BenchKit形式のJSONに変換"""
    
    # 複数の結果がある場合は平均値を計算
    if not parsed_results:
        return None
    
    # 基本情報
    result = {
        "timestamp": datetime.now().isoformat(),
        "system": system,
        "program": f"benchpark-{app}",
        "description": f"BenchPark {app} benchmark on {system}",
        "node_count": 1,  # BenchParkから取得できない場合のデフォルト
        "process_count": 1,
        "thread_count": 1,
        "execution_time": 0,
        "performance_metrics": {},
        "benchpark_data": []
    }
    
    # 全結果を統合
    total_time = 0
    all_metrics = {}
    
    for parsed in parsed_results:
        if parsed is None:
            continue
            
        # 実行時間を累積
        total_time += parsed['execution_time']
        
        # メトリクスを統合
        for key, value in parsed['metrics'].items():
            if key not in all_metrics:
                all_metrics[key] = []
            all_metrics[key].append(value)
        
        # 生データを保存
        result["benchpark_data"].append(parsed['raw_data'])
    
    # 平均値を計算
    if parsed_results:
        result["execution_time"] = total_time / len(parsed_results)
        
        for key, values in all_metrics.items():
            if values:
                result["performance_metrics"][key] = sum(values) / len(values)
    
    # ノード数などの情報をBenchParkデータから抽出を試行
    for parsed in parsed_results:
        if parsed and 'raw_data' in parsed:
            raw = parsed['raw_data']
            
            # ノード数の抽出を試行
            if 'n_nodes' in raw:
                result["node_count"] = raw['n_nodes']
            elif 'nodes' in raw:
                result["node_count"] = raw['nodes']
            
            # プロセス数の抽出を試行
            if 'n_ranks' in raw:
                result["process_count"] = raw['n_ranks']
            elif 'processes' in raw:
                result["process_count"] = raw['processes']
            
            # スレッド数の抽出を試行
            if 'omp_num_threads' in raw:
                result["thread_count"] = raw['omp_num_threads']
            elif 'threads' in raw:
                result["thread_count"] = raw['threads']
    
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
    parsed_results = []
    for result_file in result_files:
        parsed = parse_benchpark_result(result_file)
        if parsed:
            parsed_results.append(parsed)
    
    if not parsed_results:
        print("No valid results found")
        sys.exit(1)
    
    # BenchKit形式に変換
    benchkit_result = convert_to_benchkit_format(parsed_results, system, app)
    
    if not benchkit_result:
        print("Failed to convert results")
        sys.exit(1)
    
    # 結果ディレクトリを作成
    os.makedirs("results", exist_ok=True)
    
    # JSONファイルとして保存
    output_file = f"results/benchpark_{system}_{app}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(output_file, 'w') as f:
        json.dump(benchkit_result, f, indent=2)
    
    print(f"Results converted and saved to: {output_file}")
    print(f"Execution time: {benchkit_result['execution_time']:.2f} seconds")
    print(f"Performance metrics: {len(benchkit_result['performance_metrics'])} items")


if __name__ == "__main__":
    main()