# Implementation Plan: API整理・リファクタリング

## Overview

BenchKit結果サーバのAPIルート構造を整理し、データ受信Blueprintの統合、パス命名の統一、SAVE_DIR管理の改善を段階的に実施する。既存テスト25件の通過を維持しながら、新パス・互換ルート・プロパティベーステストを追加する。

## Tasks

- [x] 1. `utils/results_loader.py` のSAVE_DIR/ESTIMATED_DIR引数必須化
  - [x] 1.1 `load_results_table()` に `directory` 引数を追加し、モジュール変数 `SAVE_DIR` の参照を除去する
    - `load_results_table(directory, public_only=True, ...)` の形に変更
    - 関数内の `SAVE_DIR` 参照を全て `directory` 引数に置換
    - _Requirements: 4.1, 4.4_
  - [x] 1.2 `load_estimated_results_table()` に `directory` 引数を追加し、モジュール変数 `ESTIMATED_DIR` の参照を除去する
    - `load_estimated_results_table(directory, public_only=True, ...)` の形に変更
    - 関数内の `ESTIMATED_DIR` 参照を全て `directory` 引数に置換
    - _Requirements: 4.1, 4.4_
  - [x] 1.3 `load_single_result()` と `load_multiple_results()` の `save_dir` 引数をデフォルトなしの必須引数に変更する
    - `save_dir=None` → `save_dir`（必須）に変更
    - 関数内の `if save_dir is None: save_dir = SAVE_DIR` フォールバックを削除
    - _Requirements: 4.4_
  - [x] 1.4 モジュールレベル変数 `SAVE_DIR` と `ESTIMATED_DIR` を `results_loader.py` から削除する
    - _Requirements: 4.2_

- [x] 2. `routes/results.py` の `current_app.config` 対応
  - [x] 2.1 モジュールレベル変数 `SAVE_DIR = "received"` を削除し、各ハンドラで `current_app.config["RECEIVED_DIR"]` を使用する
    - `results()`, `result_compare()`, `result_detail()`, `show_result()` の各ハンドラを更新
    - `check_file_permission()` と `serve_confidential_file()` の呼び出し箇所も更新
    - `load_results_table()`, `load_single_result()`, `load_multiple_results()` の呼び出しに `directory` / `save_dir` 引数を追加
    - _Requirements: 4.1, 4.3_

- [x] 3. `routes/estimated.py` の `current_app.config` 対応 + URLプレフィックス変更
  - [x] 3.1 モジュールレベル変数 `ESTIMATE_DIR = "estimated_results"` を削除し、各ハンドラで `current_app.config["ESTIMATED_DIR"]` を使用する
    - `estimated_results()`, `show_estimated_result()` の各ハンドラを更新
    - `load_estimated_results_table()` の呼び出しに `directory` 引数を追加
    - _Requirements: 4.1, 4.3, 5.2_

- [x] 4. Checkpoint - 既存テスト通過確認
  - Ensure all tests pass, ask the user if questions arise.
  - 既存テスト25件が `results_loader.py` と `routes/` の変更後も通過することを確認
  - テスト内の `loader.SAVE_DIR` 参照がある場合は修正する

- [x] 5. `routes/api.py` の新規作成（api_bp統合、新パス + 互換ルート）
  - [x] 5.1 `routes/api.py` を新規作成し、`api_bp` Blueprintを定義する
    - `receive.py` の `require_api_key()`, `save_json_file()` を移植
    - `upload_tgz.py` の `is_valid_uuid()`, PA Dataアップロードロジックを移植
    - 全ハンドラで `current_app.config["RECEIVED_DIR"]` / `current_app.config["ESTIMATED_DIR"]` を使用
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4_
  - [x] 5.2 新パスのエンドポイントを実装する
    - `POST /api/ingest/result` → `ingest_result()`
    - `POST /api/ingest/estimate` → `ingest_estimate()`
    - `POST /api/ingest/padata` → `ingest_padata()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 5.3 互換ルート（deprecatedログ付き）を実装する
    - `POST /write-api` → `compat_write_api()` が `ingest_result()` を呼び出し
    - `POST /write-est` → `compat_write_est()` が `ingest_estimate()` を呼び出し
    - `POST /upload-tgz` → `compat_upload_tgz()` が `ingest_padata()` を呼び出し
    - 各互換ルートで `current_app.logger.warning()` によるdeprecatedログを出力
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 6. `app.py` のBlueprint登録変更
  - [x] 6.1 `receive_bp` と `upload_bp` のimportを `api_bp` に変更し、Blueprint登録を更新する
    - `from routes.api import api_bp` に変更
    - `app.register_blueprint(api_bp, url_prefix=prefix)` で登録
    - `estimated_bp` のurl_prefixを `f"{prefix}/estimated"` に変更
    - `receive_bp`, `upload_bp` のimportと登録を削除
    - _Requirements: 2.1, 2.2, 5.2, 5.4_

- [x] 7. `app_dev.py` のモジュール変数書き換え削除
  - [x] 7.1 `create_dev_app()` から `loader.SAVE_DIR`, `loader.ESTIMATED_DIR`, `results_route.SAVE_DIR`, `estimated_route.ESTIMATE_DIR` の直接書き換えを削除する
    - `app.config["RECEIVED_DIR"]` と `app.config["ESTIMATED_DIR"]` の設定のみで動作するようにする
    - `estimated_bp` のurl_prefixを `/estimated` に変更
    - _Requirements: 4.5_

- [x] 8. `templates/_navigation.html` のURL更新と `scripts/send_results.sh` の新パス対応
  - [x] 8.1 `_navigation.html` の推定結果リンクを `/estimated_results` → `/estimated` に変更する
    - _Requirements: 5.3_
  - [x] 8.2 `scripts/send_results.sh` のAPIパスを新パスに更新する
    - `/write-api` → `/api/ingest/result`
    - `/upload-tgz` → `/api/ingest/padata`
    - _Requirements: 3.4_

- [x] 9. 旧ファイル（`receive.py`, `upload_tgz.py`）の削除
  - [x] 9.1 `routes/receive.py` と `routes/upload_tgz.py` を削除する
    - `app.py` や他のファイルからの参照が残っていないことを確認
    - _Requirements: 6.1, 6.2_

- [x] 10. Checkpoint - 既存テスト25件の通過確認
  - Ensure all tests pass, ask the user if questions arise.
  - 全リファクタリング完了後に既存テスト25件が通過することを確認
  - テスト内の旧Blueprint参照（`receive_bp`, `upload_bp`）やモジュール変数参照を修正
  - _Requirements: 7.1_

- [x] 11. 新パス・互換ルートのテスト追加
  - [x] 11.1 `result_server/tests/test_api_routes.py` を新規作成し、新パスと互換ルートのユニットテストを実装する
    - Flask `test_client()` を使用
    - `/api/ingest/result`, `/api/ingest/estimate`, `/api/ingest/padata` への正常リクエストテスト
    - `/write-api`, `/write-est`, `/upload-tgz` への正常リクエストテスト（互換ルート）
    - APIキー認証エラーテスト（401レスポンス）
    - deprecatedログ出力の確認テスト
    - `/estimated/` でのアクセス確認テスト
    - _Requirements: 7.2, 7.3_

  - [ ]* 11.2 Property 1のプロパティベーステストを実装する
    - **Property 1: APIプレフィックスの一貫性**
    - Flaskアプリのルールを列挙し、ingest系エンドポイント（互換ルート除く）が全て `/api/ingest/` で始まることを検証
    - **Validates: Requirements 1.1**

  - [ ]* 11.3 Property 2のプロパティベーステストを実装する
    - **Property 2: レスポンス形式の保全**
    - hypothesisで任意のJSON辞書を生成し、`/api/ingest/result` へPOSTした際のレスポンスキーセットが `{status, id, timestamp, json_file}` であることを検証
    - **Validates: Requirements 1.5**

  - [ ]* 11.4 Property 3のプロパティベーステストを実装する
    - **Property 3: APIキー認証の統一性**
    - hypothesisで任意のAPIキー文字列を生成し、正しいキーなら認証通過、不正なキーなら401が返ることを全ingestエンドポイントで検証
    - **Validates: Requirements 2.4**

  - [ ]* 11.5 Property 4のプロパティベーステストを実装する
    - **Property 4: 旧パスと新パスのレスポンス等価性**
    - hypothesisで任意のJSON辞書を生成し、旧パスと新パスに同一リクエストを送信してレスポンスのキーセットが一致することを検証
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 11.6 Property 5のプロパティベーステストを実装する
    - **Property 5: ディレクトリ設定の伝播**
    - hypothesisで任意のディレクトリ名を生成し、`app.config["RECEIVED_DIR"]` に設定後、結果受信でそのディレクトリにファイルが作成されることを検証
    - **Validates: Requirements 4.1, 4.3, 4.4**

- [x] 12. Final checkpoint - 全テスト通過確認
  - Ensure all tests pass, ask the user if questions arise.
  - 既存テスト25件 + 新規テストが全て通過することを確認

## Notes

- タスク1〜3でSAVE_DIR管理を先に改善し、タスク4で既存テストの通過を確認してからBlueprint統合に進む
- タスク `*` 付きはオプション（プロパティベーステスト）でスキップ可能
- 各タスクは設計ドキュメントの対応コンポーネントを参照
- チェックポイントで段階的に動作を検証
- プロパティベーステストはhypothesisライブラリを使用
