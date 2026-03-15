# Implementation Plan: ベクトル型メトリクスのグラフ表示機能

## Overview

Flask結果サーバにベクトル型メトリクスのグラフ表示（Chart.js CDN）、詳細ページ、比較ページ、リグレッション比較機能を段階的に実装する。バックエンド（データローダー）→ ルーティング → テンプレート → フロントエンド（Chart.js）の順に構築し、各ステップで動作確認可能な状態を維持する。

## Tasks

- [x] 1. results_loader.py にデータ読み込み関数を追加
  - [x] 1.1 `load_single_result(filename, save_dir)` 関数を追加
    - 指定ファイル名のJSONを読み込み dict で返す。ファイルが存在しない場合は None を返す
    - `load_json_with_confidential_filter()` は使わず、単純なJSON読み込みとする（権限チェックはルート側で実施）
    - _Requirements: 2.1, 2.6, 11.1_
  - [x] 1.2 `load_multiple_results(filenames, save_dir)` 関数を追加
    - 各ファイルを `load_single_result()` で読み込み、タイムスタンプ昇順でソートしたリストを返す
    - 戻り値: `[{"filename": str, "timestamp": str, "data": dict}, ...]`
    - タイムスタンプはファイル名から `YYYYMMDD_HHMMSS` パターンで抽出
    - _Requirements: 8.2, 9.1_
  - [x] 1.3 `load_results_table()` を拡張して `has_vector`, `detail_link`, `filename` を各rowに追加
    - `metrics.vector` の有無で `has_vector` フラグを設定
    - `has_vector=True` の場合のみ `detail_link` に `/results/detail/<filename>` のURLを設定
    - `filename` にJSONファイル名を設定（比較ページ遷移用）
    - 既存の columns リストは変更しない（テンプレート側で新カラムを追加）
    - _Requirements: 1.1, 1.2, 1.3, 10.1, 10.4_

- [x] 2. Checkpoint - データローダーの動作確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. routes/results.py に詳細ページ・比較ページのルートを追加
  - [x] 3.1 `/results/detail/<filename>` ルートを追加
    - `check_file_permission()` で権限チェック（既存関数を再利用）
    - `load_single_result()` でデータ取得、None なら 404
    - `result_detail.html` をレンダリング（result データを渡す）
    - _Requirements: 2.1, 2.6, 10.2, 11.1, 11.4_
  - [x] 3.2 `/results/compare` ルートを追加
    - クエリパラメータ `files` からカンマ区切りのファイル名リストを取得
    - files が空または1件のみの場合は 400 エラー
    - 各ファイルの権限チェック
    - `load_multiple_results()` でデータ取得
    - 全結果の `system` と `code` が一致しない場合はエラーメッセージ付きで結果一覧にリダイレクト
    - `result_compare.html` をレンダリング
    - _Requirements: 7.3, 7.4, 8.1, 9.1, 10.2, 11.2, 11.4_
  - [ ]* 3.3 ルーティングのユニットテスト
    - Flask test client で `/results/detail/<filename>` の 200/404 応答を確認
    - `/results/compare` の 200/400 応答を確認
    - 既存の `/results/<filename>` が変更されていないことを確認
    - _Requirements: 11.1, 11.2, 11.3_

- [x] 4. 詳細ページテンプレート（result_detail.html）を作成
  - [x] 4.1 メタ情報セクションとページ構造を作成
    - `_table_base.html` のCSS/JSを継承、`_navigation.html` を含む
    - メタ情報（code, system, Exp, FOM, FOM_unit, node_count, cpus_per_node）をテーブルで表示
    - 結果一覧への戻りリンクを含む
    - _Requirements: 2.1, 2.5_
  - [x] 4.2 ベクトル型メトリクスのグラフ描画（Chart.js）を実装
    - Chart.js CDN (`https://cdn.jsdelivr.net/npm/chart.js`) を `<script>` タグで読み込み
    - `metrics.vector` が存在する場合のみグラフセクションを表示
    - X軸: `x_axis.name` (対数スケール `type: 'logarithmic'`)、Y軸: メトリクス値
    - `table.columns` の先頭（X軸）を除く各カラムを個別の系列として描画
    - 各系列を異なる色で描画（視覚的に区別可能）
    - CDN読み込み失敗時のフォールバックメッセージ
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [x] 4.3 ベクトル型メトリクスのデータテーブルを実装
    - `table.columns` をヘッダー、`table.rows` を行としたHTMLテーブル
    - グラフの下に配置
    - X軸カラムは整数表示、メトリクスカラムは小数点以下2桁表示
    - _Requirements: 4.1, 4.2, 4.3_
  - [x] 4.4 スカラー型メトリクスセクションを実装
    - `metrics.scalar` が存在しキーが2つ以上ある場合のみ表示
    - キーが「FOM」のみの場合は非表示（メタ情報で既に表示済み）
    - 各スカラーメトリクスをキー名と値のペアで表示
    - _Requirements: 5.1, 5.2_
  - [x] 4.5 ビルド情報セクションを実装
    - `build` フィールドが存在する場合のみ表示
    - ビルドツール名（build.tool）を表示
    - `build.spack` が存在する場合: コンパイラ、MPI、パッケージ一覧を表示
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 5. 結果一覧テーブル（_results_table.html）を拡張
  - [x] 5.1 「Detail」カラムとチェックボックスカラムを追加
    - 先頭にチェックボックス列を追加（各行に `<input type="checkbox">`、value にファイル名を設定）
    - 末尾に「Detail」列を追加（`has_vector=True` の行のみリンク表示）
    - 既存の9カラム（Timestamp, SYSTEM, CODE, FOM, FOM version, Exp, Nodes, JSON, PA Data）は変更しない
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.1, 10.4_
  - [x] 5.2 比較ボタンとJavaScriptバリデーションを実装
    - テーブル下部に「比較」ボタンを追加（初期状態は無効）
    - JS: チェックボックス2件以上選択で比較ボタンを有効化
    - JS: 比較ボタンクリック時、選択されたファイル名をカンマ区切りで `/results/compare?files=f1,f2,...` に遷移
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 6. Checkpoint - 詳細ページと結果一覧の動作確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. 比較ページテンプレート（result_compare.html）を作成
  - [x] 7.1 ベクトル型メトリクスの重ね合わせグラフを実装
    - `_table_base.html` のCSS/JSを継承、`_navigation.html` を含む
    - 選択された結果が `metrics.vector` を持つ場合、同一メトリクス系列を結果ごとに異なる色で重ね合わせ描画
    - 各結果をタイムスタンプで識別可能なラベルで表示
    - X軸を対数スケールで表示
    - Chart.js CDN を使用
    - 結果一覧への戻りリンクを含む
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [x] 7.2 FOM時系列グラフを実装
    - 選択された結果の FOM 値をタイムスタンプ順にグラフで表示
    - X軸: タイムスタンプ、Y軸: FOM値
    - Chart.js CDN を使用
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 8. app_dev.py と app_dev_flask.py の統合・サンプルデータ拡張
  - [x] 8.1 app_dev.py と app_dev_flask.py を1ファイルに統合
    - app_dev_flask.py の `create_dev_app()` と `_create_stub_otp_module()` を app_dev.py に移動
    - app_dev_flask.py を削除
    - app_dev.py 内で直接 `create_dev_app()` を呼び出すように変更
    - _Requirements: 10.3_
  - [x] 8.2 リグレッションテスト用サンプルデータを追加
    - `generate_sample_data()` に同一 system+code で異なるタイムスタンプのデータを追加
    - osu_bibw_old（7日前、少し異なる値）、osu_bibw_older（14日前、さらに異なる値）
    - 既存の実データがある場合はサンプル生成をスキップする既存ロジックを維持
    - _Requirements: 8.1, 9.1_

- [x] 9. Checkpoint - 全機能の統合動作確認
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 10. プロパティベーステスト（hypothesis）
  - [ ]* 10.1 Property 1: has_vector フラグと metrics.vector の存在が一致する
    - **Property 1: has_vector フラグと metrics.vector の存在が一致する**
    - **Validates: Requirements 1.1, 1.2**
    - metrics.vector の有無をランダムに切り替えた Result_JSON を生成し、`load_results_table()` の `has_vector` フラグを検証
  - [ ]* 10.2 Property 2: load_single_result はメタ情報フィールドを保持する
    - **Property 2: load_single_result はメタ情報フィールドを保持する**
    - **Validates: Requirements 2.1**
    - ランダムなメタ情報値を持つ Result_JSON を生成し、`load_single_result()` の戻り値を検証
  - [ ]* 10.3 Property 3: グラフ系列数は table.columns の長さ - 1 に等しい
    - **Property 3: グラフ系列数は table.columns の長さ - 1 に等しい**
    - **Validates: Requirements 3.3**
    - ランダムな列数（2〜10）の vector.table を生成し、系列数 = 列数 - 1 を検証
  - [ ]* 10.4 Property 4: スカラーメトリクスセクションの表示条件
    - **Property 4: スカラーメトリクスセクションの表示条件**
    - **Validates: Requirements 5.1, 5.2**
    - ランダムなキー数（0〜5）の metrics.scalar を生成し、表示条件を検証
  - [ ]* 10.5 Property 5: ビルド情報フィールドの抽出
    - **Property 5: ビルド情報フィールドの抽出**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    - ランダムなビルド情報を持つ Result_JSON を生成し、全フィールドの取得可能性を検証
  - [ ]* 10.6 Property 6: 比較時の system+code 一致バリデーション
    - **Property 6: 比較時の system+code 一致バリデーション**
    - **Validates: Requirements 7.4**
    - ランダムな system/code の組み合わせを持つ複数結果を生成し、バリデーション結果を検証
  - [ ]* 10.7 Property 7: load_multiple_results のタイムスタンプ昇順ソート
    - **Property 7: load_multiple_results のタイムスタンプ昇順ソート**
    - **Validates: Requirements 9.1**
    - ランダムな順序のタイムスタンプを持つファイル名リストを生成し、ソート結果を検証
  - [ ]* 10.8 Property 8: metrics フィールドなしの既存結果の後方互換性
    - **Property 8: metrics フィールドなしの既存結果の後方互換性**
    - **Validates: Requirements 10.1**
    - metrics フィールドなしの Result_JSON を生成し、既存フィールドの保持と has_vector=False を検証
  - [ ]* 10.9 Property 9: confidential 結果へのアクセス制御
    - **Property 9: confidential 結果へのアクセス制御**
    - **Validates: Requirements 10.2, 11.4**
    - confidential タグ付き Result_JSON を生成し、未認証アクセスでの 403 応答を検証

- [x] 11. Final checkpoint - 全テスト通過確認
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- タスク `*` 付きはオプション（スキップ可能）
- 各タスクは要件番号で追跡可能
- Chart.js は CDN 経由（`https://cdn.jsdelivr.net/npm/chart.js`）で読み込み、ビルドツール不要
- テストは `pytest` + `hypothesis` を使用（`result_server/tests/` ディレクトリに配置）
- 実データが `_dev_data/main/received` に存在する場合はそれを活用
