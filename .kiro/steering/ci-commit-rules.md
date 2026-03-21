---
inclusion: auto
---

# Git & CI ルール

## コミットメッセージ

### CIフィルタタグ
コミットメッセージでCIの実行範囲を制御できる。ユーザーが対象を限定する指示をした場合、自動的にタグを付与すること。

構文: `[key:value]` （ブラケット＋コロン形式）

| タグ | 効果 | 例 |
|------|------|-----|
| `[code:値]` | 指定プログラムのみ実行 | `[code:qws]` |
| `[system:値]` | 指定システムのみ実行 | `[system:MiyabiG]` |
| `[skip-ci]` | CI実行をスキップ | |
| `[park-only]` | BenchParkパイプラインのみ | |
| `[park-send]` | BenchPark結果送信のみ | |
| `[benchpark]` | BenchParkパイプラインも実行 | |

注意:
- `code=qws` や `system=MiyabiG` のような `=` 形式は無効（CIが認識しない）
- ユーザーが「qwsだけ」「MiyabiGだけ」等と指示した場合 → `[code:qws] [system:MiyabiG]` に変換
- result_server のみの変更は `[skip-ci]` を付与（ベンチマーク実行不要）

### コミットメッセージの書き方
- 英語で記述
- conventional commits 形式: `feat:`, `fix:`, `chore:`, `docs:` 等
- CIタグはメッセージ末尾に付与

例: `feat: add estimation pipeline [code:qws] [system:MiyabiG]`

## ブランチ
- 作業ブランチ: `develop`
- プッシュ先: `origin develop`
- PowerShellでの `git push` のstderr出力はエラーではない（正常動作）

## コミット対象の確認
- `git status` で変更内容を確認してからコミット
- 意図しないファイルが含まれていないか確認
- ユーザーが明示的に指示していないファイル変更は確認を取る
