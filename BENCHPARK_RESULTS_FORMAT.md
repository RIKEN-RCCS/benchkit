# BenchPark結果ファイル形式

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

現在の暫定実装：
- 各実験を個別のJSONファイルとして出力
- 最初に見つかったメトリクス値を代表FOMとして使用
- メッセージサイズ情報は失われる

将来の拡張：
- ベクトル的なFOM構造のサポート
- メッセージサイズごとの値を配列として保持
- グラフ表示のためのデータ構造
