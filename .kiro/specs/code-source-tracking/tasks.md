# 実装計画: コードソース追跡機能

## 概要

BenchKitフレームワークにソースコード追跡機能を追加する。`bk_functions.sh` に `bk_fetch_source` 関数を実装し、`result.sh` で `results/source_info.env` を読み込んで Result_JSON に `source_info` を含め、`results_loader.py` と `_results_table.html` で表示する。各ステップは前のステップに依存し、最終的にすべてを結合する。

## タスク

- [x] 1. `bk_fetch_source` 関数の実装 (`scripts/bk_functions.sh`)
  - [x] 1.1 `bk_fetch_source` 関数のコア実装を追加
    - `bk_functions.sh` の末尾に `bk_fetch_source` 関数を追加する
    - シグネチャ: `bk_fetch_source <source> <dest_dir> [branch]`
    - ソース種別の自動判定ロジック: `http://`/`https://` で始まるか `.git` で終わる → git、それ以外 → file
    - git clone 処理: ブランチ指定あり/なし対応、`BK_SOURCE_TYPE`, `BK_REPO_URL`, `BK_BRANCH`, `BK_COMMIT_HASH` 環境変数の設定
    - tar 展開処理: `BK_SOURCE_TYPE`, `BK_FILE_PATH`, `BK_MD5SUM` 環境変数の設定
    - md5sum のクロスプラットフォーム対応（`md5sum` / `md5 -r` フォールバック）
    - `results/source_info.env` へのエクスポート形式での書き出し（`mkdir -p results` を含む）
    - 既存ディレクトリのスキップ処理（再クローン不要時はメタデータのみ取得）
    - エラーハンドリング: git clone 失敗、アーカイブ不存在、tar 展開失敗時に stderr 出力 + 戻り値 1
    - POSIX互換（`#!/bin/sh`）を維持すること
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [ ]* 1.2 `bk_fetch_source` のソース種別判定プロパティテストを作成
    - **Property 1: ソース種別の自動判定**
    - ランダムなURL文字列・ファイルパス文字列を生成し、判定ロジックが正しく git/file を返すことを検証
    - Hypothesis を使用し、subprocess 経由でシェル関数をテスト
    - **Validates: Requirements 2.2, 2.3**

  - [ ]* 1.3 `bk_fetch_source` のエラーハンドリングユニットテストを作成
    - 存在しないアーカイブファイルでエラー戻り値 1 を返すことを検証
    - 不正なURLで git clone 失敗時にエラー戻り値 1 を返すことを検証
    - _Requirements: 2.7, 2.8_

- [x] 2. チェックポイント - bk_fetch_source のテスト確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問する。

- [x] 3. `result.sh` の `source_info` JSON 出力対応
  - [x] 3.1 `result.sh` に `results/source_info.env` 読み込みロジックを追加
    - スクリプト冒頭（FOM ブロック解析ループの前）で `results/source_info.env` の存在確認と読み込みを実装
    - `BK_SOURCE_TYPE=git` の場合: `source_type`, `repo_url`, `branch`, `commit_hash` を含む JSON オブジェクトを構築
    - `BK_SOURCE_TYPE=file` の場合: `source_type`, `file_path`, `md5sum` を含む JSON オブジェクトを構築
    - ファイルが存在しない場合: `source_info_block="null"` を設定
    - `BK_SOURCE_TYPE` が git/file 以外の場合: `source_info_block="null"` を設定
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 `write_result_json` 関数に `source_info` ブロックを追加
    - `write_result_json` 関数内の JSON 出力テンプレートに `"source_info": $source_info_block` を追加
    - 既存の JSON 構造を壊さないよう、適切な位置にカンマ区切りで挿入
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 3.3 `result.sh` の source_info.env ラウンドトリッププロパティテストを作成
    - **Property 2: source_info.env の書き出し/読み込みラウンドトリップ**
    - ランダムな source_info データ（git/file 両方）を生成し、env ファイル経由で正しい JSON が生成されることを検証
    - **Validates: Requirements 1.1, 1.2, 1.3, 3.1, 3.2, 3.3**

  - [ ]* 3.4 `result.sh` の後方互換性ユニットテストを作成
    - `results/source_info.env` なしの既存形式が正常処理されること（`source_info: null`）を検証
    - `results/source_info.env` ありで `source_info` が正しく JSON に含まれることを検証
    - _Requirements: 1.4, 6.2_

- [x] 4. チェックポイント - result.sh のテスト確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問する。

- [x] 5. `results_loader.py` の `source_info` 読み込み対応
  - [x] 5.1 `_build_row` 関数に `source_info` と `source_hash` の処理を追加
    - `data.get("source_info", None)` で source_info を取得
    - git 型: `source_hash` を `<branch>@<commit_hash先頭7桁>` 形式で生成
    - file 型: `source_hash` を `<md5sum先頭8桁>` 形式で生成
    - source_info が None または dict でない場合: `source_hash = "-"`
    - `row` dict に `source_info` と `source_hash` を追加
    - _Requirements: 5.1, 5.2_

  - [x] 5.2 `columns` 定義に `("Branch/Hash", "source_hash")` を追加
    - `load_results_table` 関数内の `columns` リストに追加
    - _Requirements: 5.3_

  - [ ]* 5.3 `results_loader` の source_info ラウンドトリッププロパティテストを作成
    - **Property 5: results_loader の source_info ラウンドトリップ**
    - ランダムな Result_JSON データを生成し、`_build_row` が `source_info` と `source_hash` を正しく設定することを検証
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 5.4 `results_loader` の source_hash フォーマットプロパティテストを作成
    - **Property 4: source_hash 表示文字列のフォーマット**
    - ランダムな source_info オブジェクトを生成し、git 型は `<branch>@<7桁>` 形式、file 型は `<8桁>` 形式、null は `-` となることを検証
    - **Validates: Requirements 4.3, 4.5, 4.6**

  - [ ]* 5.5 `results_loader` のユニットテストを作成
    - source_info なしの既存 JSON でエラーなく行構築されることを検証
    - source_info ありの JSON で source_hash が正しく生成されることを検証
    - columns リストに `("Branch/Hash", "source_hash")` が含まれることを検証
    - _Requirements: 5.1, 5.2, 5.3, 6.1_

- [x] 6. `_results_table.html` のソース情報表示対応
  - [x] 6.1 CODE 列の条件付きハイパーリンク表示を実装
    - `source_info.source_type == "git"` の場合: CODE 値を `repo_url` へのハイパーリンク（`<a>` タグ、`target="_blank"`）として表示
    - `source_info.source_type == "file"` の場合: CODE 値に `file_path` を `title` 属性（ツールチップ）として表示
    - `source_info` が null の場合: 現在と同じプレーンテキスト表示
    - _Requirements: 4.1, 4.2, 4.4_

  - [x] 6.2 「Branch/Hash」列の表示を実装
    - `columns` に追加された `source_hash` キーの値を表示
    - ヘッダー行のツールチップ定義を追加
    - フィルター行に空の `<th>` を追加
    - _Requirements: 4.3, 4.4, 4.5, 4.6_

  - [ ]* 6.3 テンプレートのレンダリングプロパティテストを作成
    - **Property 7: CODE列のレンダリング条件**
    - ランダムな source_info を含む行データで Jinja2 テンプレートをレンダリングし、git 型は `<a>` タグ、file 型は `title` 属性、null はプレーンテキストとなることを検証
    - **Validates: Requirements 4.1, 4.2**

- [x] 7. チェックポイント - 表示層のテスト確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問する。

- [x] 8. 結合と後方互換性の確認
  - [x] 8.1 ハッシュ値フォーマットのプロパティテストを作成
    - **Property 3: ハッシュ値のフォーマット検証**
    - ランダムな40桁/32桁16進数文字列を生成し、commit_hash が40桁、md5sum が32桁であることを検証
    - **Validates: Requirements 1.5, 1.6**

  - [ ]* 8.2 後方互換性の統合テストを作成
    - `source_info` フィールドが存在しない既存 Result_JSON がエラーなく表示されることを検証
    - `bk_fetch_source` を使用しない既存 build.sh が正常動作することを検証
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 9. 最終チェックポイント - 全テスト通過確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問する。

## 備考

- `*` マーク付きのタスクはオプションであり、MVP では省略可能
- 各タスクは特定の要件を参照しており、トレーサビリティを確保
- チェックポイントで段階的に検証を実施
- プロパティテストは Hypothesis ライブラリを使用し、普遍的な正当性を検証
- ユニットテストは具体的なエッジケースとエラー条件を検証
- シェルスクリプトは POSIX 互換（`#!/bin/sh`）を維持
- `result.sh` は既存の jq 依存を活用して JSON 構築
- `results/source_info.env` パスは `artifacts/` ではなく `results/` 配下
