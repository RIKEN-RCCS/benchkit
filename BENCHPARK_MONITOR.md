# BenchParkモニター機能

BenchKitにBenchParkフレームワークのモニター機能を追加しました。この機能により、BenchParkで管理されるベンチマークの結果を自動的に監視・取り込み、既存の結果表示システムで表示できます。

## 概要

### モニター方針
- **BenchPark**: 独立してRambleでジョブを実行
- **BenchKit**: BenchParkを監視し、結果を取り込んで表示
- **簡素化されたlist.csv**: システムとアプリの組み合わせのみを管理

### 主要コンポーネント

### `config/benchpark-monitor/list.csv` - BenchPark監視対象の定義

#### 2. スクリプト群
- `scripts/benchpark_matrix_generate.sh`: BenchPark用GitLab CI YAML生成
- `scripts/benchpark_functions.sh`: 共通関数ライブラリ
- `scripts/benchpark_runner.sh`: BenchPark実行管理
- `scripts/convert_benchpark_results.py`: 結果変換スクリプト

## 使用方法

### 1. BenchPark監視対象の設定

`config/benchpark-monitor/list.csv`でシステムとアプリの組み合わせを定義：

```csv
system,app,description
fugaku,qws,QWS benchmark on Fugaku system
miyabi-g,qws,QWS benchmark on MiyabiG system
miyabi-c,qws,QWS benchmark on MiyabiC system
```

### 2. GitLab CI設定の生成

```bash
# 全システム・アプリでCI設定を生成
bash scripts/benchpark_matrix_generate.sh

# 特定システムのみ
bash scripts/benchpark_matrix_generate.sh system=fugaku

# 特定アプリのみ
bash scripts/benchpark_matrix_generate.sh app=qws

# 複数指定
bash scripts/benchpark_matrix_generate.sh system=fugaku,miyabi-g app=qws
```

生成されるファイル: `.gitlab-ci.benchpark.yml`

### 3. CI実行フロー

#### Stage 1: benchpark_setup
- BenchParkワークスペースの初期化
- 実験・システム設定の確認
- Spack/Ramble環境の準備

#### Stage 2: benchpark_run
- Spackでのビルド実行
- Rambleでのベンチマーク実行
- ジョブ投入完了まで

#### Stage 3: benchpark_results
- Rambleジョブ完了の待機
- 結果の変換（BenchPark → BenchKit形式）
- 結果ファイルの生成

## 技術詳細

### BenchPark結果の変換

`convert_benchpark_results.py`は以下の変換を行います：

1. **Ramble結果の検索**: `benchpark-workspace/{system}/{app}/experiments/*/results/*.json`
2. **メトリクス抽出**: 実行時間、パフォーマンス指標
3. **BenchKit形式変換**: 既存の結果表示システムと互換性のあるJSON形式
4. **結果保存**: `results/benchpark_{system}_{app}_{timestamp}.json`

### 変換されるデータ構造

```json
{
  "timestamp": "2026-01-08T12:00:00",
  "system": "fugaku",
  "program": "benchpark-qws",
  "description": "BenchPark qws benchmark on fugaku",
  "node_count": 1,
  "process_count": 48,
  "thread_count": 1,
  "execution_time": 123.45,
  "performance_metrics": {
    "flops": 1234567890,
    "memory_bandwidth": 98765
  },
  "benchpark_data": [
    // 元のBenchPark結果データ
  ]
}
```

### システム対応

現在対応しているシステム：

- **fugaku**: Fugaku（理研）
- **miyabi-g**: MiyabiG（理研）
- **miyabi-c**: MiyabiC（理研）

新しいシステムを追加する場合は、`scripts/benchpark_functions.sh`の`get_benchpark_system_tag()`関数を更新してください。

## BenchParkとの連携

### 前提条件

1. **BenchParkインストール**: システムに既存のBenchParkがインストール済み
   - Fugaku: `/vol0004/apps/benchpark`
   - その他: `$BENCHPARK_ROOT`環境変数または`PATH`から自動検出
2. **実験設定**: BenchParkインストール内に`experiments/{app}/experiment.py`が存在
3. **システム設定**: BenchParkインストール内に`systems/{system}/system.py`が存在
4. **Spack/Ramble**: BenchParkインストールに含まれる環境を使用

### GitHub監視機能の活用

BenchParkの`checkout-versions.yaml`と`remote-urls.yaml`を活用して：

- アプリケーションの更新を自動検出
- 依存パッケージの更新を監視
- 定期的なベンチマーク実行をトリガー

## 既存機能との統合

### 結果表示システム
- 変換された結果は既存の`result_server`で表示
- システム情報は`result_server/utils/system_info.py`で管理
- ツールチップ機能も利用可能

### CI制御機能
- コミットメッセージによる制御: `[system:fugaku] [app:qws]`
- APIトリガー変数との連携
- 既存のCI制御ルールと同様の仕組み

## 注意事項

### パフォーマンス
- BenchParkジョブは長時間実行される可能性があります
- Rambleジョブの完了待機にタイムアウト（1時間）を設定

### エラーハンドリング
- BenchPark結果が見つからない場合は警告を出力
- 変換に失敗した場合はエラーで終了
- ワークスペースが見つからない場合は適切なエラーメッセージ

### ファイル管理
- BenchParkワークスペースは`benchpark-workspace/`に作成
- 結果ファイルは`results/`ディレクトリに保存
- アーティファクトの保存期間は1週間

## 今後の拡張予定

1. **より多くのアプリケーション対応**
2. **結果解析機能の強化**
3. **自動レポート生成**
4. **パフォーマンス比較機能**
5. **GitHub Webhookとの連携**

## トラブルシューティング

### よくある問題

1. **BenchPark結果が見つからない**
   - Rambleジョブが正常に完了しているか確認
   - ワークスペースパスが正しいか確認

2. **変換エラー**
   - BenchPark結果のJSON形式を確認
   - Python依存関係を確認

3. **ジョブタイムアウト**
   - Rambleジョブの実行時間を確認
   - タイムアウト設定の調整を検討

詳細なトラブルシューティング情報は`TROUBLESHOOTING_SYSTEMS.md`を参照してください。