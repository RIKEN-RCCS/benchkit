# BenchPark開発時のコミットメッセージ制御

## 重要: コミットメッセージによるCI制御

BenchPark機能の開発時は、**必ず**コミットメッセージに制御タグを含めてください。

### 制御タグの種類

#### 1. `[park-only]` - BenchParkのみ実行
**用途**: BenchPark機能の開発・テスト時

**効果**:
- BenchKit（既存ベンチマーク）のジョブは実行されない
- BenchParkモニター機能のジョブのみ実行
- CI実行時間を大幅に短縮

**使用例**:
```bash
git commit -m "Fix BenchPark job submission

[park-only]

- Update ramble workspace path
- Improve job completion detection"
```

#### 2. `[benchpark]` - BenchPark関連ファイル変更時
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

#### 3. タグなし - 通常のCI実行
**用途**: BenchKit機能の開発・修正時

**効果**:
- BenchKitのジョブのみ実行
- BenchParkモニター機能は実行されない

### チェックリスト

BenchPark関連の変更をコミットする前に確認してください：

- [ ] **BenchPark機能のみテスト**: `[park-only]`を含める
  - `scripts/benchpark_*.sh`の修正
  - `scripts/benchpark_functions.sh`の修正
  - `BENCHPARK_TODO.md`の更新
  
- [ ] **BenchPark設定変更**: `[benchpark]`を含める
  - `config/benchpark-monitor/list.csv`の変更
  - `BENCHPARK_MONITOR.md`の更新
  
- [ ] **既存機能の修正**: タグなし
  - `programs/*/`の修正
  - `scripts/matrix_generate.sh`の修正
  - `ADD_APP.md`の更新

### 注意事項

⚠️ **重要**: コミットメッセージに制御タグを忘れると、不要なジョブが実行されます
- BenchPark開発時に`[park-only]`を忘れると、kitのジョブも実行される
- CI実行時間が大幅に増加する
- リソースの無駄遣いになる

### 参考: CI制御ルール

`.gitlab-ci.yml`の制御ルール：

```yaml
# BenchPark専用実行
- if: '$CI_COMMIT_MESSAGE =~ /\[park-only\]/'
  when: always  # BenchParkのみ実行

# BenchPark関連ファイル変更
- if: '$CI_COMMIT_MESSAGE =~ /\[benchpark\]/'
  when: always  # 通常のCI実行

# 通常のCI実行
- when: always  # BenchKitのみ実行
```
