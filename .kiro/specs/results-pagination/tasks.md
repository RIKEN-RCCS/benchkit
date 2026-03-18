# 実装計画: 結果一覧ページネーション

## 概要

`results_loader.py`にページネーション計算ユーティリティとサーバーサイドフィルタを追加し、Flask ルートでクエリパラメータを処理、共通`_pagination.html`パーシャルで全対象ページにページネーションUIを提供する。既存のクライアントサイドフィルタをサーバーサイドに移行し、フィルタ条件をページネーションリンクに保持する。

## Tasks

- [x] 1. ページネーション計算ユーティリティの実装
  - [x] 1.1 `paginate_list()` ヘルパー関数を `result_server/utils/results_loader.py` に追加
    - リスト、page（1始まり）、per_page を受け取り、スライス済みリストと `pagination_info` 辞書を返す
    - `total_pages = max(1, ceil(total / per_page))` で計算
    - `page` が範囲外の場合はクランプ（1未満→1、total_pages超→total_pages）
    - 結果0件の場合は `total_pages=1`、空リストを返す
    - _Requirements: 1.1, 1.2, 1.3, 7.1, 7.2, 7.3, 7.4_

  - [ ]* 1.2 Property 1 のプロパティテスト作成
    - **Property 1: ページネーションによるリスト分割の正確性**
    - 全ページの結果を結合すると元リストと一致（欠落なし、重複なし、順序保持）
    - `result_server/tests/test_pagination_properties.py` に作成
    - **Validates: Requirements 1.1, 7.1, 7.2**

  - [ ]* 1.3 Property 2 のプロパティテスト作成
    - **Property 2: 総ページ数の計算**
    - `total_pages == max(1, ceil(total / per_page))` を検証
    - **Validates: Requirements 5.3, 7.3, 7.4**

  - [ ]* 1.4 Property 3 のプロパティテスト作成
    - **Property 3: 範囲外ページ番号のクランプ**
    - `page < 1` → 1、`page > total_pages` → `total_pages` にクランプされることを検証
    - **Validates: Requirements 1.4**

- [x] 2. `load_results_table()` のページネーション・フィルタ対応
  - [x] 2.1 `load_results_table()` にページネーション・フィルタパラメータを追加
    - `page`, `per_page`, `filter_system`, `filter_code`, `filter_exp` パラメータを追加
    - 戻り値を `(rows, columns, pagination_info)` に変更
    - フィルタなし時: ファイル名リストをスライスして対象ページのJSONのみ読み込み
    - フィルタあり時: 全JSON読み込み後にフィルタ適用、結果リストをスライス
    - `per_page` は `[50, 100, 200]` のいずれかに制限、範囲外はデフォルト100
    - _Requirements: 1.1, 1.2, 1.3, 4.1, 5.1, 5.3_

  - [x] 2.2 `load_estimated_results_table()` に同様のページネーション・フィルタ対応を追加
    - `load_results_table()` と同じシグネチャ変更を適用
    - _Requirements: 3.3_

  - [x] 2.3 `get_filter_options()` 関数を追加
    - 全JSONファイルからフィルタドロップダウンの選択肢（systems, codes, exps）を抽出して返す
    - _Requirements: 4.1_

  - [ ]* 2.4 Property 4 のプロパティテスト作成
    - **Property 4: フィルタ適用後の結果の正確性**
    - ページネーション後の全行がフィルタ条件に一致することを検証
    - **Validates: Requirements 4.1**

- [x] 3. チェックポイント - テスト実行確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Flask ルートのクエリパラメータ処理
  - [x] 4.1 `routes/results.py` の `results()` と `results_confidential()` を更新
    - `request.args` から `page`, `per_page`, `system`, `code`, `exp` を取得
    - `per_page` のバリデーション（`[50, 100, 200]` 以外はデフォルト100）
    - `page` が範囲外の場合はフィルタ条件を保持してリダイレクト（302）
    - `render_template()` に `pagination` と `filter_options` を渡す
    - _Requirements: 1.4, 4.2, 4.3, 5.2, 6.1, 6.2, 6.3_

  - [x] 4.2 `routes/estimated.py` の `estimated_results()` を更新
    - `results.py` と同様のクエリパラメータ処理を追加
    - _Requirements: 3.3, 6.4_

- [x] 5. ページネーションUIテンプレートの作成
  - [x] 5.1 `_pagination.html` 共通パーシャルを作成
    - 「Page X of Y」表示、First/Previous/Next/Last リンク
    - Previous は `page==1` で disabled、Next は `page==total_pages` で disabled
    - First/Last リンク
    - 表示件数セレクタ（50/100/200）、変更時にpage=1にリセット
    - フィルタ適用後の総件数表示（「Showing N results」）
    - 全リンクにフィルタ条件をクエリパラメータとして保持
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.3, 4.4, 5.1, 5.2_

  - [ ]* 5.2 Property 5 のプロパティテスト作成
    - **Property 5: ナビゲーションボタンの状態**
    - `page==1` で Previous 無効、`page==total_pages` で Next 無効を検証
    - **Validates: Requirements 2.2, 2.3, 2.4, 2.5**

  - [ ]* 5.3 Property 6 のプロパティテスト作成
    - **Property 6: ページネーションUIの必須要素**
    - レンダリング結果に「Page X of Y」、First、Last、総件数が含まれることを検証
    - **Validates: Requirements 2.1, 2.6, 4.4**

  - [ ]* 5.4 Property 7 のプロパティテスト作成
    - **Property 7: ページネーションリンクのフィルタ保持**
    - ページネーションリンクのURLにフィルタパラメータが保持されることを検証
    - **Validates: Requirements 4.3**

- [x] 6. 対象ページテンプレートへの統合
  - [x] 6.1 `results.html` にページネーションUIとサーバーサイドフィルタを統合
    - `_pagination.html` をテーブルの上部と下部に `{% include %}` で挿入
    - サーバーサイドフィルタドロップダウン（SYSTEM, CODE, Exp）を追加
    - 既存のキーワード検索（`filterInput`）を維持
    - _Requirements: 2.7, 3.1, 6.1_

  - [x] 6.2 `results_confidential.html` にページネーションUIとサーバーサイドフィルタを統合
    - `results.html` と同様の変更を適用
    - 認証状態に基づくアクセス制御を維持
    - _Requirements: 2.7, 3.2, 6.3_

  - [x] 6.3 `estimated_results.html` にページネーションUIとサーバーサイドフィルタを統合
    - `_pagination.html` をテーブルの上部と下部に挿入
    - estimated用のフィルタドロップダウンを追加
    - 認証状態に基づくアクセス制御を維持
    - _Requirements: 2.7, 3.3, 6.4_

  - [x] 6.4 `_results_table.html` のフィルタをサーバーサイドフィルタに変更
    - クライアントサイドの `applyFilters()` JavaScript をサーバーサイドフィルタ（フォーム送信/リンク遷移）に置き換え
    - フィルタ変更時に `page=1` にリセット
    - Compare チェックボックス機能を維持
    - _Requirements: 4.2, 6.1, 6.2, 6.5_

- [x] 7. チェックポイント - テスト実行確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. ユニットテストの作成
  - [x] 8.1 `result_server/tests/test_pagination.py` にページネーションユニットテストを作成
    - `paginate_list()` のデフォルトパラメータ動作
    - 結果0件で `total_pages=1` が返却される
    - `per_page` 不正値（75等）がデフォルト100にフォールバック
    - ページ範囲外のリダイレクト動作
    - フィルタ適用後のページネーション
    - 表示件数変更時のページリセット
    - 既存機能（Compare、認証制御）の維持確認
    - _Requirements: 1.2, 1.4, 5.3, 6.1, 6.2, 6.3, 6.4, 6.5, 7.4_

- [x] 9. 最終チェックポイント - 全テスト実行確認
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` 付きタスクはオプション（スキップ可能）
- 各タスクは要件番号で追跡可能
- チェックポイントで段階的に動作確認
- プロパティテストは hypothesis を使用し、各プロパティごとに独立したテスト関数で実装
- テンプレート内のユーザー向けテキスト（Page X of Y、First、Last、Previous、Next、Showing N results 等）は全て英語で記述
