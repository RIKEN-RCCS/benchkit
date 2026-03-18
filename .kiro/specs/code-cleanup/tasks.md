# 実装計画: result_server コードクリーンアップ

## 概要

result_server コードベースのリファクタリングを段階的に実施する。重複コード統合、不要コード除去、テンプレート共通化、マジックナンバー定数化を行い、既存の動作は一切変更しない。各ステップで既存テスト（90テスト）がパスすることを確認する。

## タスク

- [x] 1. マジックナンバーの定数化と不要コードの除去
  - [x] 1.1 `utils/results_loader.py` にページサイズ定数を追加し、既存のマジックナンバーを置換する
    - `ALLOWED_PER_PAGE = (50, 100, 200)` と `DEFAULT_PER_PAGE = 100` を定義
    - `load_results_table()` と `load_estimated_results_table()` 内の `per_page not in (50, 100, 200)` を `per_page not in ALLOWED_PER_PAGE` に置換
    - `per_page = 100` のフォールバックを `per_page = DEFAULT_PER_PAGE` に置換
    - _要件: 8.1, 8.2, 8.3_

  - [x] 1.2 `routes/results.py` と `routes/estimated.py` の `per_page` バリデーションで `results_loader` の定数を参照するよう変更する
    - `from utils.results_loader import ALLOWED_PER_PAGE, DEFAULT_PER_PAGE` を追加
    - `per_page not in (50, 100, 200)` → `per_page not in ALLOWED_PER_PAGE`
    - `per_page = 100` → `per_page = DEFAULT_PER_PAGE`
    - _要件: 8.3, 8.4_

  - [x] 1.3 不要コードを除去する
    - `app.py`: コメントアウトされたコード（`#app.redis = r_conn`, `#app.redis_prefix = key_prefix`, 旧 secret_key 設定等）を除去
    - `result_file.py`: コメントアウトされた `#SAVE_DIR`、旧関数シグネチャ、デバッグ用 `#print(...)` 文を除去
    - `routes/results.py`: 未使用の `os` インポートを除去（使用していない場合）
    - `routes/estimated.py`: 未使用の `os` インポートを除去（使用していない場合）
    - _要件: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 1.4 Property 2 のプロパティベーステストを作成する
    - **Property 2: per_page バリデーションの正しさ**
    - Hypothesis を使用して任意の整数値に対する per_page バリデーションの正しさを検証
    - **検証対象: 要件 3.2, 8.1, 8.2**

- [x] 2. チェックポイント - 既存テストの確認
  - 既存テスト（90テスト）がすべてパスすることを確認する。問題があればユーザーに確認する。

- [x] 3. フィルタマッチング関数とフィルタオプション抽出関数の統合
  - [x] 3.1 `utils/results_loader.py` にフィールドマッピング定数を追加し、`_matches_filters()` を統合する
    - `RESULT_FIELD_MAP = {"system": "system", "code": "code", "exp": "Exp"}` を定義
    - `ESTIMATED_FIELD_MAP = {"system": "benchmark_system", "code": "code", "exp": "exp"}` を定義
    - `_matches_filters()` に `field_map` パラメータを追加し、マッピングに基づいてフィルタ判定を行う
    - `_matches_estimated_filters()` を削除し、呼び出し元を `_matches_filters(data, ..., field_map=ESTIMATED_FIELD_MAP)` に変更
    - `load_results_table()` 内の呼び出しを `_matches_filters(data, ..., field_map=RESULT_FIELD_MAP)` に変更
    - _要件: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 3.2 Property 3 のプロパティベーステストを作成する
    - **Property 3: フィルタマッチングの等価性**
    - Hypothesis を使用して統合前後のフィルタマッチング結果が同一であることを検証
    - **検証対象: 要件 4.4**

  - [x] 3.3 `utils/results_loader.py` の `get_filter_options()` と `get_estimated_filter_options()` を統合する
    - `get_filter_options()` に `field_map` パラメータを追加（デフォルト: `RESULT_FIELD_MAP`）
    - `field_map` に基づいて systems/codes/exps のフィールド名を動的に参照
    - `get_estimated_filter_options()` を削除
    - `routes/estimated.py` の呼び出しを `get_filter_options(..., field_map=ESTIMATED_FIELD_MAP)` に変更
    - _要件: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 3.4 Property 4 のプロパティベーステストを作成する
    - **Property 4: フィルタオプション抽出の等価性**
    - Hypothesis を使用して統合前後のフィルタオプション抽出結果が同一であることを検証
    - **検証対象: 要件 5.4**

- [x] 4. チェックポイント - 既存テストの確認
  - 既存テスト（90テスト）がすべてパスすることを確認する。問題があればユーザーに確認する。

- [x] 5. ファイル権限チェックの統合
  - [x] 5.1 `utils/result_file.py` に共通 `check_file_permission()` 関数を追加する
    - `session` から `authenticated`/`user_email` を取得し、`UserStore` から `affiliations` を取得
    - confidential タグとの交差判定を行い、権限不足時に `abort(403)` を発生
    - `routes/results.py` の `check_file_permission()` と `routes/estimated.py` の `_check_file_permission()` を削除し、共通関数をインポートして使用
    - _要件: 1.1, 1.2, 1.3_

  - [ ]* 5.2 Property 1 のプロパティベーステストを作成する
    - **Property 1: 権限チェックの等価性**
    - Hypothesis を使用して任意のタグ・認証状態・所属の組み合わせに対する権限判定の正しさを検証
    - **検証対象: 要件 1.3**

- [x] 6. クエリパラメータ抽出の共通化と結果一覧ルートの統合
  - [x] 6.1 `routes/results.py` に `extract_query_params()` ヘルパー関数を追加する
    - `request.args` から `page`, `per_page`, `system`, `code`, `exp` を一括抽出
    - `per_page` が `ALLOWED_PER_PAGE` に含まれない場合は `DEFAULT_PER_PAGE` を使用
    - `routes/estimated.py` からもインポートして使用
    - _要件: 3.1, 3.2, 3.3, 3.4_

  - [x] 6.2 `routes/results.py` に `_render_results_list()` 内部共通関数を追加し、`results()` と `results_confidential()` を統合する
    - `_render_results_list(public_only, template_name, redirect_endpoint)` を作成
    - クエリパラメータ抽出（`extract_query_params()` 使用）、セッション情報取得、データ読み込み、ページ範囲外リダイレクト、テンプレートレンダリングを一括処理
    - `results()` は `_render_results_list(public_only=True, template_name="results.html", redirect_endpoint="results.results")` を呼び出す
    - `results_confidential()` は `_render_results_list(public_only=False, template_name="results_confidential.html", redirect_endpoint="results.results_confidential")` を呼び出す
    - _要件: 2.1, 2.2, 2.3_

- [x] 7. チェックポイント - 既存テストの確認
  - 既存テスト（90テスト）がすべてパスすることを確認する。問題があればユーザーに確認する。

- [x] 8. 管理画面のユーザーリスト準備ロジック統合
  - [x] 8.1 `routes/admin.py` に `_get_users_with_totp_status()` ヘルパー関数を追加する
    - `get_user_store()` から全ユーザーを取得し、各ユーザーに `has_totp` フラグを付与して返す
    - `users()`, `add_user()`, `reinvite_user()` の重複する `for u in all_users: u["has_totp"] = ...` ループを共通関数に置換
    - _要件: 9.1, 9.2, 9.3_

  - [ ]* 8.2 Property 5 のプロパティベーステストを作成する
    - **Property 5: ユーザーリスト準備の正しさ**
    - Hypothesis を使用して `_get_users_with_totp_status()` が正しく `has_totp` フラグを付与することを検証
    - **検証対象: 要件 9.3**

- [x] 9. テンプレートの重複排除
  - [x] 9.1 `_results_base.html` 基底テンプレートを作成する
    - 共通レイアウト（DOCTYPE, head, _table_base.html include, _navigation.html include, title ブロック, heading ブロック, auth_warning ブロック, 検索入力, content ブロック）を定義
    - _要件: 6.1, 6.2_

  - [x] 9.2 `results.html`, `results_confidential.html`, `estimated_results.html` を `_results_base.html` を継承する形に書き換える
    - 各テンプレートで title, heading, auth_warning, content ブロックのみを定義
    - `results.html`: title="Results", heading="Results", content に `_results_table.html` を include
    - `results_confidential.html`: title="Confidential Results", heading="Confidential Results", auth_warning に認証警告を表示, content に `_results_table.html` を include
    - `estimated_results.html`: title="Estimated Results", heading="Estimated Results", auth_warning に認証警告を表示, content に推定結果テーブルを配置
    - _要件: 6.2, 6.5_

  - [x] 9.3 `estimated_results.html` のインラインフィルタドロップダウンを `_filter_dropdowns.html` パーシャルとして抽出する
    - `_results_table.html` と同様のフィルタドロップダウン構造を共通パーシャルに抽出
    - `estimated_results.html` から `_filter_dropdowns.html` を include して使用
    - _要件: 6.3_

  - [x] 9.4 `estimated_results.html` のインラインページネーションコードが既存の `_pagination.html` を使用していることを確認する
    - 既に `{% include "_pagination.html" %}` を使用している場合は変更不要
    - インラインのページネーション HTML が残っている場合は `_pagination.html` に置換
    - _要件: 6.4_

- [x] 10. 最終チェックポイント - 全テスト確認
  - 既存テスト（90テスト）がすべてパスすることを確認する。問題があればユーザーに確認する。

## 備考

- `*` マーク付きタスクはオプション（プロパティベーステスト）であり、スキップ可能
- 各タスクは要件ドキュメントの具体的な要件番号を参照
- チェックポイントで段階的に動作確認を実施し、リグレッションを防止
- プロパティベーステストは Hypothesis ライブラリを使用し、`result_server/tests/test_code_cleanup.py` に配置
