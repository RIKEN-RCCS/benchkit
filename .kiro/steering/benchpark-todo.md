# BenchParkモニター機能 - 今後の作業事項

## 🎯 現在の状況

### ✅ 完了済み
- BenchParkモニター機能の基本実装
- GitLab CI統合（park-only, park-sendモード）
- YAML生成スクリプト（構文エラー解決済み）
- RC_GH200システムでのBenchParkパス設定
- パイプライン最適化（1ジョブ統合、アーティファクト最適化）
- 結果変換スクリプト（複数実験対応、メトリクス抽出修正）
- 結果送信スクリプトの実装
- ベクトル型メトリクス対応（OSU Micro-Benchmarks）
- スカラー型メトリクス対応（gpcnet等）
- Spackビルド情報の抽出と保存
- ノード数の自動抽出（execute_experimentスクリプトから）
- システム名の統一（RC_GH200）
- ファイル構成の整理（benchpark-bridge/ディレクトリ）
- 複数ジョブID対応（ramble on実行時）
- id_tokens設定（Jacamar-CI認証）

### 🔄 現在の状況
- RC_GH200でOSU Micro-Benchmarksとgpcnetが正常動作
- 結果変換・送信が正常動作
- mainブランチへのマージ準備完了

### ⚠️ Fugakuシステムの制約（保留）
**問題**: Fugakuではログインノードと計算ノードの環境が異なり、BenchParkの実行に制約がある
- **ログインノード**: BenchPark環境構築（setup）ができない
- **計算ノード**: 環境構築は可能だが、ジョブサブミット（`ramble on`）ができない
- **結論**: Fugakuでの実行は技術的制約により保留

**当面の方針**: QC-GH200での実行に注力し、Fugakuは将来的な課題として扱う

## 📋 今後の作業事項

### 1. 結果表示システムの改善
- [x] ベクトル型メトリクスのJSON形式対応
- [x] スカラー型メトリクスのJSON形式対応
- [x] Spackビルド情報の抽出と保存
- [ ] 結果表示システムでのグラフ表示機能追加
  - メッセージサイズ vs バンド幅のプロット
  - 複数メトリクスの同時表示（Bandwidth, P50, P90, P99）
  - スカラー型メトリクスの表形式表示

### 2. システム・アプリケーション拡張
- [x] RC_GH200でOSU Micro-Benchmarks動作確認
- [x] RC_GH200でgpcnet動作確認
- [ ] ~~Fugakuシステムでの動作確認~~ → 保留（技術的制約）
- [ ] 他のBenchParkアプリケーションの追加
  - HPCG
  - AMG2023
  - その他のベンチマーク
- [ ] 複数システム・アプリの並行実行テスト

### 3. BenchPark定義ファイル自動生成（将来的な拡張）
- [ ] BenchKit登録アプリからBenchPark定義を生成するツール
- [ ] package.py生成機能
- [ ] application.py生成機能
- [ ] experiment.py生成機能
- 詳細は`.kiro/steering/benchpark-generator-plan.md`を参照

## 🚫 Fugakuシステムの技術的制約

### 問題の詳細
Fugakuシステムでは、ログインノードと計算ノードの環境が分離されており、BenchParkの実行フローに制約があります：

1. **ログインノードの制約**
   - BenchPark環境構築（`benchpark setup`）が実行できない
   - コンパイル環境が計算ノード用に設定されている
   - クロスコンパイル環境の制約

2. **計算ノードの制約**
   - 環境構築（setup）は可能
   - しかし、ジョブサブミット（`ramble on`）ができない
   - 計算ノードからPJMへのジョブ投入が制限されている

3. **ワークフロー上の問題**
   ```
   ログインノード: setup不可 → run不可
   計算ノード: setup可能 → run不可（ジョブサブミット不可）
   ```

### 将来的な解決策の検討
- [ ] ログインノードでのクロスコンパイル環境整備
- [ ] 計算ノードからのジョブサブミット方法の調査
- [ ] BenchPark側での対応（setup/runの分離実行）
- [ ] 代替ワークフロー（手動実行）の検討

### 当面の対応
**QC-GH200での実行に注力**し、Fugakuは技術的制約が解決されるまで保留とします。

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
RC_GH200 (OSU): /home/users/nakamura/benchpark_output/work2026/GH200_nvhpc/osu-micro-benchmarks/workspace
RC_GH200 (gpcnet): /home/users/nakamura/benchpark_output/work2026/GH200/gpcnet_network_test/workspace
fugaku: /vol0004/apps/benchpark（保留中）
```

### 重要なルール
- `benchpark-workspace/`は巨大なため、アーティファクトとして保存禁止
- 結果ファイル（`results/`）のみを保存
- YAML生成時はコロン（:）の使用に注意

### パイプライン構成
- BenchKitと並行実行（同じstage: generate/trigger）
- park-onlyモードでBenchPark専用テスト可能（フル実行）
- park-sendモードで結果送信のみテスト可能
- コミットメッセージ制御: `[park-only]`, `[park-send]`, `[benchpark]`, `[skip-ci]`

## 🚨 既知の問題と対策

### 1. ~~python3コマンド問題（Singularityコンテナ環境）~~
**解決済み**: Runner環境のPATH設定を修正して解決

### 2. ~~YAML構文エラー~~
**解決済み**: echo文からコロン削除、既存matrix_generate.sh方式採用

### 3. ~~CSV読み込み問題~~
**解決済み**: ファイル末尾改行、whileループ修正

### 4. ~~アーティファクトアップロード問題~~
**解決済み**: custom executorのPATH設定を修正して解決

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
benchpark-bridge/
├── config/
│   └── apps.csv                    # 監視対象定義
└── scripts/
    ├── common.sh                   # 共通関数
    ├── ci_generator.sh             # CI YAML生成
    ├── runner.sh                   # BenchPark実行
    └── result_converter.py         # 結果変換

.kiro/steering/
├── benchpark-todo.md               # 作業事項
├── benchpark-results-format.md     # 結果形式仕様
├── benchpark-development.md        # 開発ルール
└── benchpark-generator-plan.md     # Generator計画
```

## 🎯 最終目標

1. **完全動作**: RC_GH200で複数のBenchParkアプリが正常実行 ✅
2. **結果統合**: BenchKit結果表示システムでの表示 ✅
3. **安定運用**: mainブランチでの継続的な監視機能（準備完了）
4. **拡張性**: 他システム・アプリの容易な追加 ✅