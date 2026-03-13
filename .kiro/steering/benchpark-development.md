# BenchPark開発時のコミットメッセージ制御

## 重要: コミットメッセージによるCI制御

BenchPark機能の開発時は、**必ず**コミットメッセージに制御タグを含めてください。

### 制御タグの種類

#### 1. `[park-only]` - BenchParkのみ実行
**用途**: BenchPark機能の開発・テスト時

**効果**:
- BenchKit（既存ベンチマーク）のジョブは実行されない
- BenchParkモニター機能のジョブのみ実行
- setup, run, wait, 結果変換、結果送信まで実行される
- CI実行時間を大幅に短縮

**使用例**:
```bash
git commit -m "Fix BenchPark job submission

[park-only]

- Update ramble workspace path
- Improve job completion detection"
```

#### 2. `[park-send]` - BenchPark結果送信のみ
**用途**: 既存の結果を再送信したい時

**効果**:
- BenchKit（既存ベンチマーク）のジョブは実行されない
- BenchParkの実行はスキップ（setup, run, waitをスキップ）
- 結果変換と結果送信のみ実行される
- 既に実行済みのBenchPark結果を再送信する場合に使用

**使用例**:
```bash
git commit -m "Resend BenchPark results

[park-send]

- Fix result conversion logic
- Resend existing results to server"
```

#### 3. `[benchpark]` - BenchPark関連ファイル変更時
**用途**: BenchPark設定ファイルやドキュメント更新時

**効果**:
- BenchParkモニター機能のジョブが実行される
- BenchKitジョブも実行される（通常のCI）

**使用例**:
```bash
git commit -m "Update BenchPark configuration

[benchpark]

- Add new benchmark to list.csv
- Update system configuration"
```

#### 4. `[skip-ci]` - CI/CD完全スキップ
**用途**: ドキュメント更新やCI不要な変更時

**効果**:
- 全てのCI/CDジョブがスキップされる
- BenchPark関連の変更でも使用可能

**使用例**:
```bash
git commit -m "Update documentation

[skip-ci]

- Fix typos in BENCHPARK_TODO.md
- Update BENCHPARK_RESULTS_FORMAT.md"
```

#### 4. タグなし - 通常のCI実行
**用途**: BenchKit機能の開発・修正時

**効果**:
- BenchKitのジョブのみ実行
- BenchParkモニター機能は実行されない

### チェックリスト

BenchPark関連の変更をコミットする前に確認してください：

- [ ] **BenchPark機能のフルテスト（結果送信あり）**: `[park-only]`を含める
  - `benchpark-bridge/scripts/`の修正
  - `benchpark-bridge/config/apps.csv`の修正
  - setup, run, 結果変換、結果送信まで実行される

- [ ] **BenchPark結果送信のみ**: `[park-send]`を含める
  - 結果変換ロジックの修正
  - 既存の結果を再送信したい場合
  - setup, runはスキップされる
  
- [ ] **ドキュメントのみ更新**: `[skip-ci]`を含める
  - `.kiro/steering/benchpark-*.md`の更新
  - その他ドキュメントファイル
  
- [ ] **BenchPark設定変更**: `[benchpark]`を含める
  - `benchpark-bridge/config/apps.csv`の変更
  
- [ ] **既存機能の修正**: タグなし
  - `programs/*/`の修正
  - `scripts/matrix_generate.sh`の修正
  - `ADD_APP.md`の更新

### 注意事項

⚠️ **重要**: コミットメッセージに制御タグを忘れると、不要なジョブが実行されます
- BenchPark開発時に`[park-only]`を忘れると、kitのジョブも実行される
- CI実行時間が大幅に増加する
- リソースの無駄遣いになる

💡 **ヒント**: ドキュメントのみの更新時は`[skip-ci]`を使用してCI/CDを完全スキップできます

### 参考: CI制御ルール

`.gitlab-ci.yml`の制御ルール：

```yaml
# CI/CD完全スキップ
- if: '$CI_COMMIT_MESSAGE =~ /\[skip-ci\]/'
  when: never  # 全ジョブスキップ

# BenchPark専用実行（フル）
- if: '$CI_COMMIT_MESSAGE =~ /\[park-only\]/'
  when: always  # BenchParkのみ実行（setup, run, wait, 変換, 送信）

# BenchPark結果送信のみ
- if: '$CI_COMMIT_MESSAGE =~ /\[park-send\]/'
  when: always  # BenchPark結果送信のみ（変換, 送信）

# BenchPark関連ファイル変更
- if: '$CI_COMMIT_MESSAGE =~ /\[benchpark\]/'
  when: always  # 通常のCI実行

# 通常のCI実行
- when: always  # BenchKitのみ実行
```


---

## 🎯 開発の基本原則

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
benchpark-bridge/                # BenchPark統合ディレクトリ
├── config/
│   └── apps.csv                 # 監視対象定義
└── scripts/
    ├── common.sh                # 共通関数
    ├── ci_generator.sh          # CI YAML生成
    ├── runner.sh                # BenchPark実行
    └── result_converter.py      # 結果変換

.kiro/steering/
└── benchpark-*.md               # BenchPark関連ドキュメント

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

## 🔧 CI統合の詳細ルール

### 1. **ステージ分離**
- BenchPark専用ステージを使用（`benchpark_generate`, `benchpark_trigger`）
- 既存ステージ（`generate`, `trigger`）は変更禁止

### 2. **実行条件の厳格化**
BenchParkモニター機能は以下の場合**のみ**実行：

```yaml
rules:
  - if: '$benchpark == "true"'           # API変数での明示指定
  - if: '$CI_COMMIT_MESSAGE =~ /\[benchpark\]/'  # コミットメッセージ指定
  - if: '$CI_COMMIT_MESSAGE =~ /\[park-only\]/'  # BenchPark専用実行
  - if: '$CI_COMMIT_MESSAGE =~ /\[park-send\]/'  # 結果送信のみ
  - changes:                             # BenchPark関連ファイル変更
      - "benchpark-bridge/**/*"
      - ".kiro/steering/benchpark-*.md"
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
git commit -m "Add benchpark feature xxx

[park-only]

- Specific change description"
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

## ⚠️ 開発時の注意事項

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

---

このルールに従うことで、BenchParkモニター機能を安全に開発・運用し、既存のBenchKit機能との共存を実現します。
