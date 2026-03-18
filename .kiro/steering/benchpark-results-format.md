---
inclusion: fileMatch
fileMatchPattern: 'benchpark-bridge/scripts/result_converter.py|result_server/templates/result_detail.html'
---

# BenchPark結果ファイル形式と技術仕様

BenchParkのRamble結果形式とBenchKit形式への変換に関する技術仕様を記録します。

---

## results.latest.txt の構造

BenchParkのRambleが生成する`results.latest.txt`ファイルの形式を記録します。

## 全体構造

```
From Workspace: workspace (hash: ...)

Experiment <実験名> figures of merit:
  Status = SUCCESS
  Tags = [...]
  
  default (null) context figures of merit:
    OMB Version = v7.5
    OMB Datatype = MPI_CHAR
  
  Exit code from execute-<ワークロード名> context figures of merit:
    modifier::exit-code::Exit code = 0
  
  Message Size: <サイズ> context figures of merit:
    <メトリクス名> = <値> <単位>
    P50 Tail <メトリクス名> = <値> <単位>
    P90 Tail <メトリクス名> = <値> <単位>
    P99 Tail <メトリクス名> = <値> <単位>
  
  Message Size: <サイズ> context figures of merit:
    ...
  
  Software definitions:
    spack packages:
      <パッケージ名> @<バージョン>
      ...

Experiment <次の実験名> figures of merit:
  ...
```

## 実験名の形式

```
<アプリ名>.<ワークロード名>.<実験ID>_mpi_<MPIプロセス数>
```

例：
- `osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2`
- `osu-micro-benchmarks.osu_bw.osu-micro-benchmarks_osu_bw_test_mpi_2`
- `osu-micro-benchmarks.osu_latency.osu-micro-benchmarks_osu_latency_test_mpi_2`
- `gpcnet.network_test.gpcnet_network_test_test_mpi_72`
- `gpcnet.network_test.gpcnet_network_test_test_mpi_144`

## コンテキストの種類

### 1. default (null) context
アプリケーション全体の情報
- OMB Version
- OMB Datatype

### 2. Exit code context
実行結果の終了コード
- `modifier::exit-code::Exit code = 0`

### 3. Message Size context
各メッセージサイズごとのパフォーマンスメトリクス

メッセージサイズ：1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576, 2097152, 4194304 (バイト)

## メトリクスの種類

### osu_bibw (Bidirectional Bandwidth)
- Bandwidth (MB/s)
- P50 Tail Bandwidth (MB/s)
- P90 Tail Bandwidth (MB/s)
- P99 Tail Bandwidth (MB/s)

### osu_bw (Unidirectional Bandwidth)
- Bandwidth (MB/s)
- P50 Tail Bandwidth (MB/s)
- P90 Tail Bandwidth (MB/s)
- P99 Tail Bandwidth (MB/s)

### osu_latency (Latency)
- Latency (us)
- P50 Tail Latency (us)
- P90 Tail Latency (us)
- P99 Tail Latency (us)

### gpcnet (スカラー型メトリクス)
- Avg RR Two-sided Lat (MiB/sec)
- Avg RR Get Lat (MiB/sec)
- Avg Multiple Allreduce (MiB/sec)

## 実際の例

### osu_bibw の例（ベクトル型）
```
Message Size: 1 context figures of merit:
Bandwidth = 6.47 MB/s
P50 Tail Bandwidth = 6.54 MB/s
P90 Tail Bandwidth = 6.89 MB/s
P99 Tail Bandwidth = 6.92 MB/s
```

### osu_latency の例（ベクトル型）
```
Message Size: 1 context figures of merit:
Latency = 1.50 us
P50 Tail Latency = 1.49 us
P90 Tail Latency = 1.52 us
P99 Tail Latency = 1.68 us
```

### gpcnet の例（スカラー型）
```
default (null) context figures of merit:
Avg RR Two-sided Lat = 1.1 MiB/sec
Avg RR Get Lat = 2.1 MiB/sec
Avg Multiple Allreduce = 2.2 MiB/sec
```

## パーサー実装の注意点

1. **実験の分割**: "Experiment " + "figures of merit:" で新しい実験を検出
2. **実験名の抽出**: "Experiment " と " figures of merit:" の間の文字列
3. **MPIプロセス数**: 実験名から `_mpi_<数値>` を抽出
4. **メトリクスの分類**: 
   - "Message Size:" コンテキスト内 → ベクトル型メトリクス
   - "default (null)" コンテキスト内 → スカラー型メトリクス
   - "::"を含むキー（exit code等）はスキップ
   - 値と単位をスペースで分割
5. **Spackパッケージ情報**: "Software definitions:" セクションから抽出
6. **ノード数**: `all_experiments`ファイルから`execute_experiment`スクリプトを特定し、`#SBATCH -N`を抽出

## BenchKit形式への変換

### 変換処理の概要

`benchpark-bridge/scripts/result_converter.py`が以下の変換を実行：

1. **Ramble結果の検索**: 
   - RC_GH200 (OSU): `/home/users/nakamura/benchpark_output/work2026/GH200_nvhpc/osu-micro-benchmarks/workspace/results.latest.txt`
   - RC_GH200 (gpcnet): `/home/users/nakamura/benchpark_output/work2026/GH200/gpcnet_network_test/workspace/results.latest.txt`
   - その他: `benchpark-workspace/{system}/{app}/experiments/*/results/*.json`

2. **メトリクス抽出**: 
   - 実験ごとに分割（"Experiment " + "figures of merit:"）
   - MPIプロセス数を実験名から抽出（`_mpi_<数値>`）
   - ベクトル型メトリクス（Message Sizeコンテキスト）とスカラー型メトリクスを分類
   - Spackパッケージ情報を抽出（Software definitionsセクション）
   - ノード数を`execute_experiment`スクリプトから抽出

3. **BenchKit形式変換**: 
   - 各実験を個別のJSONファイルとして出力
   - ベクトル型メトリクスをtable形式に変換
   - スカラー型メトリクスをmetrics.scalarに格納
   - Spackビルド情報をbuildセクションに格納

4. **結果保存**: 
   - `results/result{i}.json`（BenchKit互換形式）

### BenchKit JSON構造（新形式）

```json
{
  "code": "benchpark-osu-micro-benchmarks",
  "system": "RC_GH200",
  "Exp": "osu_bibw",
  "FOM": 6.47,
  "FOM_version": "osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2",
  "FOM_unit": "MB/s",
  "cpu_name": "-",
  "gpu_name": "-",
  "node_count": 1,
  "cpus_per_node": 2,
  "gpus_per_node": 0,
  "cpu_cores": 0,
  "uname": "-",
  "description": null,
  "confidential": null,
  "metrics": {
    "scalar": {
      "FOM": 6.47
    },
    "vector": {
      "x_axis": {
        "name": "message_size",
        "unit": "bytes"
      },
      "table": {
        "columns": ["message_size", "Bandwidth", "P50 Tail Bandwidth", "P90 Tail Bandwidth", "P99 Tail Bandwidth"],
        "rows": [
          [1, 6.47, 6.54, 6.89, 6.92],
          [2, 12.64, 12.68, 13.42, 13.82],
          [4, 25.77, 26.67, 27.63, 27.73]
        ]
      }
    }
  },
  "build": {
    "tool": "spack",
    "spack": {
      "spack_version": "0.22.0",
      "spec": "osu-micro-benchmarks %gcc@11.5.0",
      "compiler": {
        "name": "gcc",
        "version": "11.5.0"
      },
      "mpi": {
        "name": "openmpi",
        "version": "4.1.7"
      },
      "packages": [
        {"name": "gcc", "version": "11.5.0"},
        {"name": "openmpi", "version": "4.1.7"}
      ]
    }
  }
}
```

### フィールド説明

- **code**: `benchpark-{app}` 形式（BenchPark由来であることを明示）
- **system**: システム名（RC_GH200, fugaku等）
- **Exp**: ワークロード名（実験名から抽出）
- **FOM**: 代表メトリクス値（ベクトル型の場合は最大メッセージサイズの値）
- **FOM_version**: 完全な実験名
- **FOM_unit**: メトリクスの単位（MB/s, us等）
- **cpu_name**: CPU名（現在は"-"）
- **gpu_name**: GPU名（現在は"-"）
- **node_count**: ノード数（execute_experimentスクリプトから抽出）
- **cpus_per_node**: MPIプロセス数（実験名から抽出）
- **gpus_per_node**: GPU数（現在は0）
- **cpu_cores**: CPUコア数（現在は0）
- **uname**: システム情報（現在は"-"）
- **description**: 説明（null）
- **confidential**: アクセス制御用（null）
- **metrics.scalar**: スカラー型メトリクス（gpcnet等）
- **metrics.vector**: ベクトル型メトリクス（OSU等）
  - **x_axis**: X軸の定義（message_size, bytes）
  - **table**: メトリクスのテーブル（columns, rows）
- **build**: Spackビルド情報
  - **tool**: "spack"
  - **spack.compiler**: コンパイラ情報（name, version）
  - **spack.mpi**: MPI情報（name, version）
  - **spack.packages**: 全パッケージリスト

### 対応システム

現在対応しているシステム（`benchpark-bridge/scripts/common.sh`の`get_benchpark_system_tag()`で定義）：

- **RC_GH200**: QC-GH200（理研クラウド）→ タグ: `rccs_cloud_login`
- **fugaku**: Fugaku（理研）→ タグ: `fugaku_login1`（保留中）
- **miyabi-g**: MiyabiG（理研）→ タグ: TBD
- **miyabi-c**: MiyabiC（理研）→ タグ: TBD

### ワークスペースパス

システムごとのBenchParkワークスペースパス：

- **RC_GH200 (OSU)**: `/home/users/nakamura/benchpark_output/work2026/GH200_nvhpc/osu-micro-benchmarks/workspace`
- **RC_GH200 (gpcnet)**: `/home/users/nakamura/benchpark_output/work2026/GH200/gpcnet_network_test/workspace`
- **Fugaku**: `/vol0004/apps/benchpark`（保留中）
- **その他**: `benchpark-workspace/{system}/{app}`

---

## 現在の実装状況

### 実装済み機能
- 各実験を個別のJSONファイルとして出力（`result0.json`, `result1.json`, ...）
- ベクトル型メトリクスをtable形式に変換（OSU Micro-Benchmarks）
- スカラー型メトリクスをmetrics.scalarに格納（gpcnet）
- Spackビルド情報の抽出と保存（コンパイラ、MPI、パッケージリスト）
- ノード数の自動抽出（execute_experimentスクリプトから）
- 複数実験（3つ以上）の処理に対応
- BenchKit互換のJSON形式（必須フィールド完備）

### 現在の制約
- **ノード数**: execute_experimentスクリプトから抽出（取得できない場合は1）
- **CPU/GPU情報**: 現在は固定値（"-", 0）、将来的にシステム情報から取得予定
- **Spackバージョン**: 現在は固定値（0.22.0）、将来的に実際のバージョンを取得予定

---

## 将来の拡張

### 結果表示システムの改善
- グラフ表示機能の追加
  - メッセージサイズ vs バンド幅のプロット
  - 複数メトリクスの同時表示（Bandwidth, P50, P90, P99）
- スカラー型メトリクスの表形式表示
- ビルド情報の表示（コンパイラ、MPI、パッケージ）

### システム情報の自動取得
- CPU名、GPU名の自動検出
- CPUコア数の取得
- uname情報の取得

---

## 技術的注意事項

### パーサー実装のポイント
1. "Message Size:"で始まる行はコンテキスト名なのでスキップ
2. "::"を含むキー（exit code等）はスキップ
3. 値から単位を削除（スペースで分割して最初の要素を使用）
4. 実験名から`_mpi_<数値>`を抽出してMPIプロセス数を取得
5. ベクトル型とスカラー型を自動判別
6. Spackパッケージ情報を"Software definitions:"セクションから抽出
7. ノード数を`all_experiments`と`execute_experiment`から抽出

### エラーハンドリング
- ワークスペースが見つからない場合: エラー終了
- 結果ファイルが見つからない場合: エラー終了
- メトリクス抽出失敗: 警告を出力して継続
- ノード数抽出失敗: デフォルト値1を使用
- 変換失敗: エラー終了

### ファイル管理
- 結果ファイルは`results/`ディレクトリに保存
- ファイル名は`result{i}.json`形式（BenchKit互換）
- 各JSONファイルの末尾に改行を追加（BenchKit互換）
- アーティファクトとして保存（保存期間: 1週間）
