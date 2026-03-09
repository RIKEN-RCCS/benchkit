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


def extract_node_count_from_experiment(workspace_path, experiment_name):
    """実験のexecute_experimentスクリプトからノード数を抽出
    
    Args:
        workspace_path: BenchParkワークスペースのパス
        experiment_name: 実験名（例: osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2）
    
    Returns:
        int: ノード数（取得できない場合は1）
    """
    try:
        # all_experimentsファイルのパス
        all_experiments_file = os.path.join(workspace_path, "all_experiments")
        
        if not os.path.exists(all_experiments_file):
            print(f"Warning: all_experiments file not found: {all_experiments_file}")
            return 1
        
        # all_experimentsファイルを読み込み
        with open(all_experiments_file, 'r') as f:
            content = f.read()
        
        # 実験名に対応するexecute_experimentスクリプトのパスを検索
        # 例: sbatch /path/to/osu-micro-benchmarks_osu_bibw_test_mpi_2/execute_experiment
        experiment_id = experiment_name.split('.')[-1]  # 最後の部分を取得
        
        for line in content.split('\n'):
            if experiment_id in line and 'execute_experiment' in line:
                # sbatchスクリプトのパスを抽出
                parts = line.split()
                if len(parts) >= 2:
                    script_path = parts[1]
                    
                    # execute_experimentスクリプトを読み込み
                    if os.path.exists(script_path):
                        with open(script_path, 'r') as script_file:
                            script_content = script_file.read()
                        
                        # sbatchオプションから-Nの値を抽出
                        # 例: #SBATCH -N 2 または #SBATCH --nodes=2
                        import re
                        
                        # -N <数値> の形式
                        match = re.search(r'#SBATCH\s+-N\s+(\d+)', script_content)
                        if match:
                            return int(match.group(1))
                        
                        # --nodes=<数値> の形式
                        match = re.search(r'#SBATCH\s+--nodes=(\d+)', script_content)
                        if match:
                            return int(match.group(1))
                    else:
                        print(f"Warning: execute_experiment script not found: {script_path}")
                break
        
        print(f"Warning: Could not extract node count for experiment: {experiment_name}")
        return 1
        
    except Exception as e:
        print(f"Error extracting node count: {e}")
        return 1


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
    """Rambleの結果テキストファイルを解析（複数実験対応、ベクトル型メトリクス対応）
    
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
            # メトリクスを抽出（ベクトル型対応）
            vector_metrics = {}  # {message_size: {metric_name: value}}
            scalar_metrics = {}
            spack_packages = []
            mpi_processes = 2  # デフォルト
            
            # MPI プロセス数を抽出（例: mpi_2 → 2）
            if "_mpi_" in exp['name']:
                try:
                    mpi_str = exp['name'].split("_mpi_")[-1]
                    mpi_processes = int(mpi_str)
                except:
                    pass
            
            current_message_size = None
            in_software_section = False
            
            for line in exp['lines']:
                # Software definitionsセクションの検出
                if "Software definitions:" in line:
                    in_software_section = True
                    continue
                
                # Spackパッケージ情報の抽出
                if in_software_section:
                    if "spack packages:" in line:
                        continue
                    # パッケージ行: "  package-name @version"
                    if line.strip() and not line.strip().startswith("Experiment"):
                        parts = line.strip().split()
                        if len(parts) >= 2 and parts[1].startswith('@'):
                            pkg_name = parts[0]
                            pkg_version = parts[1][1:]  # @を除去
                            spack_packages.append({
                                'name': pkg_name,
                                'version': pkg_version
                            })
                    continue
                
                # Message Sizeコンテキストの検出
                if line.strip().startswith("Message Size:"):
                    try:
                        size_str = line.split("Message Size:")[1].split("context")[0].strip()
                        current_message_size = int(size_str)
                        if current_message_size not in vector_metrics:
                            vector_metrics[current_message_size] = {}
                    except:
                        current_message_size = None
                    continue
                
                # メトリクス値の抽出
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
                                    unit = value_parts[1] if len(value_parts) > 1 else ""
                                    
                                    # Message Sizeコンテキスト内のメトリクス
                                    if current_message_size is not None:
                                        vector_metrics[current_message_size][key] = {
                                            'value': value,
                                            'unit': unit
                                        }
                                    else:
                                        # スカラーメトリクス
                                        scalar_metrics[key] = {
                                            'value': value,
                                            'unit': unit
                                        }
                                except ValueError:
                                    pass
                    except:
                        pass
            
            parsed_experiments.append({
                'experiment': exp['name'],
                'workload': exp['name'].split('.')[1] if '.' in exp['name'] else 'unknown',
                'mpi_processes': mpi_processes,
                'vector_metrics': vector_metrics,
                'scalar_metrics': scalar_metrics,
                'spack_packages': spack_packages,
                'raw_data': {'lines': exp['lines']}
            })
        
        return parsed_experiments
        
    except Exception as e:
        print(f"Error parsing {result_file}: {e}")
        return []


def convert_to_benchkit_format(parsed_result, system, app, workspace_path):
    """BenchKit形式のJSONに変換（ベクトル型メトリクス対応）
    
    Args:
        parsed_result: 解析済みの実験結果
        system: システム名
        app: アプリケーション名
        workspace_path: BenchParkワークスペースのパス（ノード数抽出用）
    """
    
    if not parsed_result:
        return None
    
    # 実験名からワークロード名を抽出
    experiment_name = parsed_result.get('experiment', 'unknown')
    workload = parsed_result.get('workload', 'unknown')
    mpi_processes = parsed_result.get('mpi_processes', 1)
    
    # ノード数を抽出
    node_count = extract_node_count_from_experiment(workspace_path, experiment_name)
    
    # ベクトル型メトリクスの処理
    vector_metrics_data = parsed_result.get('vector_metrics', {})
    scalar_metrics_data = parsed_result.get('scalar_metrics', {})
    spack_packages = parsed_result.get('spack_packages', [])
    
    # FOM値の決定（最大メッセージサイズの最初のメトリクス）
    fom_value = 0
    fom_unit = ""
    fom_type = "unknown"
    
    if vector_metrics_data:
        # 最大メッセージサイズを取得
        max_msg_size = max(vector_metrics_data.keys())
        metrics_at_max = vector_metrics_data[max_msg_size]
        
        if metrics_at_max:
            # 最初のメトリクスを代表値として使用
            first_metric_name = list(metrics_at_max.keys())[0]
            fom_value = metrics_at_max[first_metric_name]['value']
            fom_unit = metrics_at_max[first_metric_name]['unit']
            fom_type = first_metric_name
    
    # ベクトル型メトリクスをtable形式に変換
    vector_table = None
    x_axis_name = "message_size"
    x_axis_unit = "bytes"
    
    if vector_metrics_data:
        # メッセージサイズでソート
        sorted_sizes = sorted(vector_metrics_data.keys())
        
        # カラム名を取得（最初のメッセージサイズから）
        if sorted_sizes:
            first_size_metrics = vector_metrics_data[sorted_sizes[0]]
            metric_names = list(first_size_metrics.keys())
            columns = ["message_size"] + metric_names
            
            # 行データを構築
            rows = []
            for msg_size in sorted_sizes:
                row = [msg_size]
                for metric_name in metric_names:
                    if metric_name in vector_metrics_data[msg_size]:
                        row.append(vector_metrics_data[msg_size][metric_name]['value'])
                    else:
                        row.append(None)
                rows.append(row)
            
            vector_table = {
                "columns": columns,
                "rows": rows
            }
    
    # Spackビルド情報の構築
    build_info = None
    if spack_packages:
        # コンパイラとMPIを特定
        compiler_name = None
        compiler_version = None
        mpi_name = None
        mpi_version = None
        
        for pkg in spack_packages:
            pkg_name = pkg['name'].lower()
            if 'gcc' in pkg_name or 'clang' in pkg_name or 'intel' in pkg_name:
                compiler_name = pkg['name']
                compiler_version = pkg['version']
            elif 'mpi' in pkg_name or pkg_name in ['openmpi', 'mpich', 'mvapich']:
                mpi_name = pkg['name']
                mpi_version = pkg['version']
        
        build_info = {
            "tool": "spack",
            "spack": {
                "spack_version": "0.22.0",  # TODO: 実際のバージョンを取得
                "spec": f"{app} %{compiler_name}@{compiler_version}" if compiler_name else f"{app}",
                "compiler": {
                    "name": compiler_name or "unknown",
                    "version": compiler_version or "unknown"
                },
                "mpi": {
                    "name": mpi_name or "unknown",
                    "version": mpi_version or "unknown"
                },
                "packages": spack_packages
            }
        }
    
    # タイムスタンプはサーバ側で自動追加されるため不要
    
    # BenchKit形式のJSON構造（新形式）
    result = {
        "code": f"benchpark-{app}",
        "system": system,
        "Exp": workload,
        "FOM": fom_value,
        "FOM_version": experiment_name,
        "FOM_unit": fom_unit,
        "cpu_name": "-",  # TODO: システム情報から取得
        "gpu_name": "-",  # TODO: システム情報から取得
        "node_count": node_count,
        "cpus_per_node": mpi_processes,
        "gpus_per_node": 0,
        "cpu_cores": 0,  # TODO: システム情報から取得
        "uname": "-",  # TODO: システム情報から取得
        "description": None,
        "confidential": None,
        "metrics": {
            "scalar": {
                "FOM": fom_value
            }
        }
    }
    
    # ベクトル型メトリクスを追加
    if vector_table:
        result["metrics"]["vector"] = {
            "x_axis": {
                "name": x_axis_name,
                "unit": x_axis_unit
            },
            "table": vector_table
        }
    
    # ビルド情報を追加
    if build_info:
        result["build"] = build_info
    
    return result


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 convert_benchpark_results.py <system> <app>")
        sys.exit(1)
    
    system = sys.argv[1]
    app = sys.argv[2]
    
    # QC-GH200専用のワークスペースパス
    if system == "RC_GH200":
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
        benchkit_result = convert_to_benchkit_format(experiment, system, app, workspace_path)
        
        if not benchkit_result:
            print(f"Failed to convert experiment {i+1}")
            continue
        
        # BenchKit互換のファイル名形式（result*.json）
        # 既存のsend_results.shがそのまま使える
        # BenchKitはresult0.jsonから始まる
        output_file = f"results/result{i}.json"
        
        with open(output_file, 'w') as f:
            json.dump(benchkit_result, f, indent=2)
            f.write('\n')  # 末尾に改行を追加（BenchKit互換）
        
        output_files.append(output_file)
        print(f"Experiment {i+1}/{len(all_experiments)}: {experiment.get('experiment', 'unknown')}")
        print(f"  FOM: {benchkit_result['FOM']}")
        print(f"  Saved to: {output_file}")
    
    print(f"\nTotal: {len(output_files)} result files created")


if __name__ == "__main__":
    main()