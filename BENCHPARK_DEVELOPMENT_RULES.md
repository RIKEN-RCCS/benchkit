# BenchParkモニター機能開発ルール

BenchParkモニター機能の開発・拡張時に従うべきルールです。mainブランチへの安全なマージを確保するため、慎重な開発を心がけてください。

## 🎯 基本原則

### 1. **既存機能への非干渉**
- BenchKit既存機能に**絶対に影響を与えない**
- 既存のファイル・ディレクトリ構造を変更しない
- 既存のCI動作を変更しない

### 2. **独立性の維持**
- BenchPark機能は完全に独立して動作
- 通常のベンチマーク開発時は実行されない
- 明示的な指定でのみ実行

### 3. **段階的開発**
- 小さな変更を積み重ねる
- 各変更で動作確認を実施
- 問題発生時の切り戻しを容易にする

---

## 📁 ファイル配置ルール

### ✅ 許可される配置
```
config/benchpark-monitor/        # BenchPark設定（新規ディレクトリ）
scripts/benchpark_*.sh           # BenchPark専用スクリプト
scripts/convert_benchpark_*.py   # BenchPark専用Python
BENCHPARK_*.md                   # BenchPark専用ドキュメント
.gitlab-ci.benchpark.yml         # 生成されるCI設定（gitignore済み）
```

### ❌ 禁止される変更
```
programs/*/                      # 既存ベンチマークプログラム
scripts/matrix_generate.sh       # 既存CI生成スクリプト
scripts/result.sh                # 既存結果処理
result_server/                   # 結果サーバ（BenchPark結果表示は例外）
system.csv, queue.csv            # 既存システム設定
```

---

## 🔧 CI統合ルール

### 1. **ステージ分離**
- BenchPark専用ステージを使用（`benchpark_generate`, `benchpark_trigger`）
- 既存ステージ（`generate`, `trigger`）は変更禁止

### 2. **実行条件の厳格化**
BenchParkモニター機能は以下の場合**のみ**実行：

```yaml
rules:
  - if: '$benchpark == "true"'           # API変数での明示指定
  - if: '$CI_COMMIT_MESSAGE =~ /\[benchpark\]/'  # コミットメッセージ指定
  - changes:                             # BenchPark関連ファイル変更
      - "config/benchpark-monitor/**/*"
      - "scripts/benchpark_*"
      - "BENCHPARK_*.md"
  - when: never                          # その他は実行しない
```

### 3. **アーティファクト管理**
- `.gitlab-ci.benchpark.yml`は`.gitignore`に追加済み
- BenchParkワークスペースも`.gitignore`に追加済み
- **重要**: `benchpark-workspace/`は巨大なため、アーティファクトとして保存禁止
- 結果ファイル（`results/`）のみを保存する

---

## 🧪 テスト・検証ルール

### 1. **機能テスト**
- [ ] BenchPark機能が正常に動作する
- [ ] 既存のBenchKit機能に影響しない
- [ ] CI実行条件が正しく動作する

### 2. **統合テスト**
- [ ] 通常のベンチマーク実行でBenchParkが動作しない
- [ ] BenchPark指定時のみ動作する
- [ ] 両方の機能が並行して動作する

### 3. **パフォーマンステスト**
- [ ] 通常のCI実行時間に影響しない
- [ ] BenchPark実行時のリソース使用量が適切

---

## 📝 開発フロー

### 1. **ブランチ戦略**
```bash
# BenchPark機能は専用ブランチで開発
git checkout -b feature/benchpark-xxx
# 小さな変更単位でコミット
git commit -m "Add benchpark feature xxx [benchpark]"
```

### 2. **マージ前チェックリスト**
- [ ] 既存機能への影響確認
- [ ] CI実行条件の動作確認
- [ ] ドキュメント更新
- [ ] テスト実行・結果確認
- [ ] コードレビュー実施

### 3. **マージ後確認**
- [ ] mainブランチでの動作確認
- [ ] 既存機能の回帰テスト
- [ ] BenchPark機能の動作確認

---

## ⚠️ 注意事項

### 1. **重いリソース使用**
- BenchPark機能はFugakuリソースを使用
- 不要な実行を避けるため、実行条件を厳格に管理
- テスト時も最小限の実行に留める

### 2. **外部依存**
- BenchParkリポジトリは外部参照（`benchpark/`はgitignore）
- Spack/Rambleの動作環境に依存
- システム固有の設定が必要

### 3. **エラーハンドリング**
- BenchPark機能のエラーが既存機能に影響しないよう設計
- 適切なエラーメッセージとログ出力
- 失敗時の切り戻し手順を明確化

---

## 🔄 継続的改善

### 1. **定期レビュー**
- BenchPark機能の使用状況確認
- パフォーマンス・リソース使用量の監視
- 必要に応じてルールの見直し

### 2. **ドキュメント更新**
- 新機能追加時のドキュメント更新
- トラブルシューティング情報の蓄積
- 使用例・ベストプラクティスの共有

---

## 📞 問題発生時の対応

1. **即座に機能を無効化**（必要に応じて）
2. **問題の切り分け**（BenchPark vs 既存機能）
3. **修正・テスト・再デプロイ**
4. **事後分析・ルール見直し**

このルールに従うことで、BenchParkモニター機能を安全に開発・運用し、既存のBenchKit機能との共存を実現します。