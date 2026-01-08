---
inclusion: fileMatch
fileMatchPattern: 'scripts/matrix_generate.sh'
---

# GitLab CI YAML生成ルール

`scripts/matrix_generate.sh`でYAMLを生成する際は、以下のルールを厳守してください：

## 基本原則
1. **scriptセクションはシンプルに保つ**
   - 複雑なシェル構文をYAML内で使用しない
   - 条件文（if文）、パイプ（|）、複雑な変数展開（${}）を避ける

2. **基本コマンドのみ使用**
   - 許可: `echo`, `bash`, `ls`, `mkdir`, `cd`, `cat`
   - 禁止: 複雑な条件文、ループ、複数行コマンド

3. **デバッグは単純なecho文で**
   - 複雑なロジックは避ける
   - 例: `echo "Debug: variable value is $var"`

4. **複雑な処理は別スクリプトに分離**
   - 必要な場合は独立したシェルスクリプトを作成
   - YAMLからは単純に `bash path/to/script.sh` で呼び出す

## 禁止事項（YAML構文エラーの原因）

### 絶対に使用禁止
- **リダイレクト**: `2>/dev/null`, `>/dev/null`, `>>file`
- **パイプ**: `command1 | command2`
- **論理演算子**: `&&`, `||`
- **特殊文字**: `===`, `---`, `***`
- **複雑な引用符**: ネストした引用符、エスケープ文字
- **条件文**: `if [[ ]]`, `case`文
- **変数展開**: `$(command)`, `${var}`（基本的な`$var`は可）

### 安全な代替案
```yaml
# 悪い例
script:
  - echo "=== Debug ===" && ls -la . || echo "Failed"
  - cat file.log 2>/dev/null || echo "No log"

# 良い例
script:
  - echo "Debug information"
  - ls -la .
  - cat file.log || echo "No log found"
```

## 悪い例（避けるべき）
```yaml
script:
  - if [[ -d results ]]; then echo "Results exists"; ls -la results/; else echo "No results"; fi
  - echo "Current directory: $(pwd)" && ls -la . || echo "Cannot list"
  - cat debug.log 2>/dev/null | head -10
```

## 良い例（推奨）
```yaml
script:
  - echo "Checking results directory"
  - ls -la results/ || echo "Results directory not found"
  - cat debug.log || echo "No debug log"
  - bash scripts/debug_info.sh
```

## YAML構文エラーを避けるために
- 引用符のエスケープに注意
- インデントを正確に保つ
- 複雑な文字列は変数に事前定義する
- 1行1コマンドの原則を守る

このルールに従うことで、GitLab CIのYAML構文エラーを防ぎ、メンテナンスしやすいコードを保てます。