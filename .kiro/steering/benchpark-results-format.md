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

## 実際の例

### osu_bibw の例
```
Message Size: 1 context figures of merit:
Bandwidth = 6.47 MB/s
P50 Tail Bandwidth = 6.54 MB/s
P90 Tail Bandwidth = 6.89 MB/s
P99 Tail Bandwidth = 6.92 MB/s
```

### osu_latency の例
```
Message Size: 1 context figures of merit:
Latency = 1.50 us
P50 Tail Latency = 1.49 us
P90 Tail Latency = 1.52 us
P99 Tail Latency = 1.68 us
```

## パーサー実装の注意点

1. **実験の分割**: "Experiment " + "figures of merit:" で新しい実験を検出
2. **実験名の抽出**: "Experiment " と " figures of merit:" の間の文字列
3. **MPIプロセス数**: 実験名から `_mpi_<数値>` を抽出
4. **メトリクスの抽出**: 
   - "Message Size:" で始まる行はコンテキスト名（スキップ）
   - その後の `" = "` を含む行がメトリクス
   - 値と単位をスペースで分割
5. **ベクトル的なFOM**: 各メッセージサイズごとに異なる値を持つ
   - 現在の実装では最初のメトリクスのみを代表値として使用
   - 将来的には全メッセージサイズの値を保持する必要がある

## BenchKit形式への変換

### 変換処理の概要

`scripts/convert_benchpark_results.py`が以下の変換を実行：

1. **Ramble結果の検索**: 
   - QC-GH200: `/home/users/nakamura/src/benchpark/r-ccs-fork/benchpark/workspace/riken-cloud-gh200-nvhpc/{app}/workspace/results.latest.txt`
   - その他: `benchpark-workspace/{system}/{app}/experiments/*/results/*.json`

2. **メトリクス抽出**: 
   - 実験ごとに分割（"Experiment " + "figures of merit:"）
   - MPIプロセス数を実験名から抽出（`_mpi_<数値>`）
   - メトリクス値を抽出（"Message Size:"行をスキップ、"::"を含むキーをスキップ）

3. **BenchKit形式変換**: 
   - 各実験を個別のJSONファイルとして出力
   - 最初に見つかったメトリクス値を代表FOMとして使用

4. **結果保存**: 
   - `results/benchpark_{system}_{app}_{experiment_name}_{timestamp}.json`

### BenchKit JSON構造

```json
{
  "code": "benchpark-osu-micro-benchmarks",
  "system": "qc-gh200",
  "FOM": "6.47",
  "FOM_version": "osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2",
  "Exp": "osu_bibw",
  "node_count": "1",
  "cpus_per_node": "2",
  "description": "dummy",
  "confidential": "null"
}
```

### フィールド説明

- **code**: `benchpark-{app}` 形式（BenchPark由来であることを明示）
- **system**: システム名（qc-gh200, fugaku等）
- **FOM**: 最初のメトリクス値（Bandwidth, Latency等）
- **FOM_version**: 完全な実験名
- **Exp**: ワークロード名（実験名から抽出）
- **node_count**: ノード数（現在は"1"固定）
- **cpus_per_node**: MPIプロセス数（実験名から抽出）
- **description**: "dummy"（将来的に拡張予定）
- **confidential**: "null"

### 対応システム

現在対応しているシステム（`scripts/benchpark_functions.sh`の`get_benchpark_system_tag()`で定義）：

- **qc-gh200**: QC-GH200（理研クラウド）→ タグ: `rccs_cloud_login`
- **fugaku**: Fugaku（理研）→ タグ: `fugaku_login1`（保留中）
- **miyabi-g**: MiyabiG（理研）→ タグ: TBD
- **miyabi-c**: MiyabiC（理研）→ タグ: TBD

### ワークスペースパス

システムごとのBenchParkワークスペースパス：

- **QC-GH200**: `/home/users/nakamura/src/benchpark/r-ccs-fork/benchpark/workspace/riken-cloud-gh200-nvhpc/{app}/workspace`
- **Fugaku**: `/vol0004/apps/benchpark`（保留中）
- **その他**: `benchpark-workspace/{system}/{app}`

---

## 現在の暫定実装と制約

## 現在の暫定実装と制約

### 実装済み機能
- 各実験を個別のJSONファイルとして出力
- 最初に見つかったメトリクス値を代表FOMとして使用
- BenchKitの既存形式に合わせた構造
- 複数実験（3つ以上）の処理に対応

### 制約・課題
- **メッセージサイズ情報の損失**: 各メッセージサイズごとの値が失われる
- **単一FOM値**: 最初のメトリクスのみを使用（P50, P90, P99は無視）
- **ベクトル的なFOM未対応**: メッセージサイズごとの配列データに未対応
- **ノード数固定**: 現在は"1"固定（BenchParkから取得できない）

---

## 将来の拡張
- ベクトル的なFOM構造のサポート
- メッセージサイズごとの値を配列として保持
- グラフ表示のためのデータ構造

## 将来の拡張

### ベクトル的なFOM構造
- 現在: 1実験=1FOM値
- 必要: 1実験=複数FOM値（メッセージサイズごと）
- 例: `{"message_size": [1, 2, 4, 8], "bandwidth": [6.47, 12.64, 25.77, 51.18]}`

### BenchKit結果サーバの拡張
- グラフ表示機能の追加
- メッセージサイズ vs バンド幅のプロット
- 複数メトリクスの同時表示（Bandwidth, P50, P90, P99）

### データ構造の拡張案

```json
{
  "code": "benchpark-osu-micro-benchmarks",
  "system": "qc-gh200",
  "FOM": "6.47",
  "FOM_version": "osu-micro-benchmarks.osu_bibw",
  "Exp": "osu_bibw",
  "node_count": "1",
  "cpus_per_node": "2",
  "vector_metrics": {
    "message_size": [1, 2, 4, 8, 16, 32, 64, 128],
    "Bandwidth": [6.47, 12.64, 25.77, 51.18, 102.24, 201.54, 387.03, 774.60],
    "P50_Tail_Bandwidth": [6.54, 12.68, 26.67, 51.20, 102.56, 200.00, 387.88, 779.30],
    "P90_Tail_Bandwidth": [6.89, 13.42, 27.63, 54.70, 107.74, 215.13, 414.91, 829.82],
    "P99_Tail_Bandwidth": [6.92, 13.82, 27.73, 55.36, 110.15, 221.07, 425.96, 844.88]
  },
  "description": "OSU Bidirectional Bandwidth benchmark",
  "confidential": "null"
}
```

---

## 技術的注意事項

### パーサー実装のポイント
1. "Message Size:"で始まる行はコンテキスト名なのでスキップ
2. "::"を含むキー（exit code等）はスキップ
3. 値から単位を削除（スペースで分割して最初の要素を使用）
4. 実験名から`_mpi_<数値>`を抽出してMPIプロセス数を取得

### エラーハンドリング
- ワークスペースが見つからない場合: エラー終了
- 結果ファイルが見つからない場合: エラー終了
- メトリクス抽出失敗: 警告を出力して継続
- 変換失敗: エラー終了

### ファイル管理
- 結果ファイルは`results/`ディレクトリに保存
- ファイル名に実験名とタイムスタンプを含める
- アーティファクトとして保存（保存期間: 1週間）
