# BenchParkモニター機能 - 今後の作業事項

## 🎯 現在の状況

### ✅ 完了済み
- BenchParkモニター機能の基本実装
- GitLab CI統合（park-onlyモード）
- YAML生成スクリプト（構文エラー解決済み）
- QC-GH200システムでのBenchParkパス設定
- パイプライン最適化（1ジョブ統合、アーティファクト最適化）

### 🔄 現在の問題
- **python3コマンドが見つからない**: QC-GH200システムでpython3が利用できない
- **Singularityコンテナ環境**: GitLab RunnerがSingularityコンテナ内で動作
- **Python環境構築が必要**: コンテナ内でvenv等でPython環境を作成する必要
- BenchParkワークスペース初期化は成功

## 📋 今後の作業事項

### 1. 環境問題の解決
- [ ] **Singularityコンテナ内でのPython環境構築**
  - [ ] venv環境の作成
  - [ ] 必要なPythonパッケージのインストール
  - [ ] BenchParkランナースクリプトでの環境アクティベート
- [ ] QC-GH200でのpython3環境設定
- [ ] 必要に応じてmodule loadコマンドの追加
- [ ] 環境変数PATHの調整

### 2. BenchPark実行環境の整備
- [ ] Spack/Ramble環境の確認
- [ ] OSU Micro-Benchmarksの実行テスト
- [ ] 結果ファイル生成の確認

### 3. 結果変換機能の実装
- [ ] `convert_benchpark_results.py`の動作確認
- [ ] BenchKit形式への変換テスト
- [ ] 結果表示システムとの統合確認

### 4. システム拡張
- [ ] Fugakuシステムでの動作確認
- [ ] 他のBenchParkアプリケーションの追加
- [ ] 複数システム・アプリの並行実行テスト

## 🔧 Singularityコンテナ対応策

### Python環境構築手順
1. **venv環境作成**: コンテナ内で永続的なPython環境を構築
2. **環境アクティベート**: BenchParkランナースクリプトで自動アクティベート
3. **依存関係インストール**: Spack, Ramble, 必要なPythonパッケージ
4. **パス設定**: 仮想環境のPythonを優先使用

### 実装方針
- `benchpark_runner.sh`でPython環境の自動セットアップ
- 初回実行時に環境構築、以降は既存環境を使用
- エラーハンドリングで環境問題を適切に報告

## 🔧 技術的注意事項

### BenchParkパス設定
```bash
# 現在の設定
fugaku: /vol0004/apps/benchpark
qc-gh200: /etc/gitlab-runner/benchkit_monitoring/benchpark
```

### 重要なルール
- `benchpark-workspace/`は巨大なため、アーティファクトとして保存禁止
- 結果ファイル（`results/`）のみを保存
- YAML生成時はコロン（:）の使用に注意

### パイプライン構成
- BenchKitと並行実行（同じstage: generate/trigger）
- park-onlyモードでBenchPark専用テスト可能
- コミットメッセージ制御: `[park-only]`, `[benchpark]`

## 🚨 既知の問題と対策

### 1. python3コマンド問題（Singularityコンテナ環境）
**症状**: `python3: command not found`
**環境**: GitLab RunnerがSingularityコンテナ内で動作
**対策候補**:
- コンテナ内でvenv環境作成
- Python仮想環境のアクティベート
- BenchParkランナースクリプトでの環境設定
- 必要パッケージ（spack, ramble等）のインストール

### 2. YAML構文エラー
**解決済み**: echo文からコロン削除、既存matrix_generate.sh方式採用

### 3. CSV読み込み問題
**解決済み**: ファイル末尾改行、whileループ修正

## 📝 開発ガイドライン

### コミット方針
- 機能ごとに個別コミット
- `[park-only]`でBenchPark専用テスト
- 既存BenchKit機能への影響を避ける

### テスト方針
- featureブランチでの段階的テスト
- 問題解決後にmainブランチマージ
- 既存機能との回帰テスト実施

### ファイル構成
```
config/benchpark-monitor/list.csv    # 監視対象定義
scripts/benchpark_*.sh               # BenchPark専用スクリプト
scripts/convert_benchpark_results.py # 結果変換
BENCHPARK_MONITOR.md                 # 機能説明
BENCHPARK_DEVELOPMENT_RULES.md       # 開発ルール
```

## 🎯 最終目標

1. **完全動作**: QC-GH200でOSU Micro-Benchmarksが正常実行
2. **結果統合**: BenchKit結果表示システムでの表示
3. **安定運用**: mainブランチでの継続的な監視機能
4. **拡張性**: 他システム・アプリの容易な追加