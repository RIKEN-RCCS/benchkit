# 実装計画: 性能推定機能のBenchKit統合

## 概要

既存の `build → run → send_results` パイプラインに `estimate → send_estimate` ステージを追加する。共通基盤から順にボトムアップで実装し、最後にCIパイプラインに統合する。テストはPython hypothesis + subprocess でシェルスクリプトを検証する。

## タスク

- [x] 1. 推定共通関数ライブラリの作成
  - [x] 1.1 `scripts/estimate_common.sh` を作成する
    - グローバル変数（est_code, est_exp, est_fom, est_system, est_node_count, est_benchmark_*, est_current_*, est_future_*）を定義
    - `read_values` 関数: jqでResult_JSONからcode, exp, FOM, system, node_countを読み取りグローバル変数に設定
    - ファイル不在時・FOMフィールド欠落時はstderrにエラーメッセージを出力して `exit 1`
    - `print_json` 関数: グローバル変数からresult_server互換のEstimate_JSONを標準出力に出力
    - `performance_ratio` は `est_current_fom / est_future_fom` をawkで計算（future_fomが0の場合は0を出力）
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 5.1, 5.2, 5.3, 5.4_

  - [ ]* 1.2 Property 1: read_values ラウンドトリップテスト
    - **Property 1: read_values ラウンドトリップ**
    - hypothesisでランダムなcode, exp, FOM, system, node_countを生成し、一時Result_JSONを作成
    - subprocess経由で `read_values` を実行し、グローバル変数の値が元のJSON値と一致することを検証
    - **Validates: Requirements 1.1**

  - [ ]* 1.3 Property 2: print_json フォーマット完全性テスト
    - **Property 2: print_json フォーマット完全性**
    - hypothesisでランダムなグローバル変数値を生成し、subprocess経由で `print_json` を実行
    - 出力が有効なJSONであり、全必須フィールド（code, exp, benchmark_system, benchmark_fom, benchmark_nodes, current_system, future_system, performance_ratio）が存在し、値が一致することを検証
    - **Validates: Requirements 1.2, 1.3, 1.4, 5.1, 5.2, 5.3**

  - [ ]* 1.4 Property 3: performance_ratio 計算の正確性テスト
    - **Property 3: performance_ratio 計算の正確性**
    - hypothesisで正の数値ペア（current_fom, future_fom）を生成し、`print_json` 出力のperformance_ratioが `current_fom / future_fom` と浮動小数点精度の範囲内で一致することを検証
    - **Validates: Requirements 5.4**

  - [ ]* 1.5 read_values エラーケースのユニットテスト
    - 存在しないファイルパスを渡した場合の非ゼロ終了コード確認
    - FOMフィールドを含まないJSONを渡した場合の非ゼロ終了コード確認
    - _Requirements: 1.5, 1.6_

- [x] 2. アプリケーション別推定スクリプトの作成
  - [x] 2.1 `programs/qws/estimate.sh` を作成する
    - `source scripts/estimate_common.sh` で共通関数を読み込み
    - 第1引数としてResult_JSONファイルパスを受け取る
    - `read_values` でベンチマーク結果を読み取り
    - ダミー推定モデル: current_fom = FOM × 10, future_fom = FOM × 2, method = "scale-mock"
    - `print_json` で `results/estimate_<code>_0.json` に出力
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 6.1, 7.1, 7.2, 7.3_

  - [ ]* 2.2 Property 7: ダミー推定モデルのスケーリングテスト
    - **Property 7: ダミー推定モデルのスケーリング**
    - hypothesisで正のFOM値を生成し、一時Result_JSONを作成
    - subprocess経由で `programs/qws/estimate.sh` を実行
    - 出力JSONの current_system.fom = FOM × 10, future_system.fom = FOM × 2, method = "scale-mock" を検証
    - **Validates: Requirements 7.2, 7.3**

- [x] 3. チェックポイント - 共通基盤とアプリ別スクリプトの動作確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問してください。

- [x] 4. CI実行用ラッパーと送信スクリプトの作成
  - [x] 4.1 `scripts/run_estimate.sh` を作成する
    - 第1引数としてプログラムコード名を受け取る
    - `programs/<code>/estimate.sh` の存在確認（不在時は警告メッセージ出力して正常終了）
    - `results/result*.json` を検出し、各ファイルに対して `estimate.sh` を実行
    - result*.jsonが存在しない場合は警告メッセージ出力して正常終了
    - 推定結果ファイルの存在確認メッセージ出力
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 4.2 Property 9: run_estimate.sh の全結果処理テスト
    - **Property 9: run_estimate.sh の全結果処理**
    - hypothesisでresult*.jsonファイル数（1〜5）を生成し、一時ディレクトリにダミーResult_JSONを配置
    - subprocess経由で `run_estimate.sh` を実行し、各result*.jsonに対してestimate.shが1回ずつ呼び出されることを検証
    - **Validates: Requirements 9.2**

  - [x] 4.3 `scripts/send_estimate.sh` を作成する
    - `results/` 内の `estimate*.json` を検出し、各ファイルを `/api/ingest/estimate` にPOST
    - 環境変数 `RESULT_SERVER` からサーバURL、`RESULT_SERVER_KEY` からAPIキーを取得
    - ファイルが存在しない場合は警告メッセージ出力して正常終了
    - HTTP POST失敗時は非ゼロ終了
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 4.4 Property 8: send_estimate.sh の全ファイル送信テスト
    - **Property 8: send_estimate.sh の全ファイル送信**
    - hypothesisでestimate*.jsonファイル数（1〜5）を生成し、モックサーバ（またはcurlモック）で送信を検証
    - 送信されたファイル数が元のファイル数と一致することを検証
    - **Validates: Requirements 3.1, 3.2**

- [x] 5. チェックポイント - ラッパーと送信スクリプトの動作確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問してください。

- [x] 6. job_functions.sh への推定ジョブ生成関数追加
  - [x] 6.1 `scripts/job_functions.sh` に推定関連の定数と関数を追加する
    - `ESTIMATE_SYSTEMS="MiyabiG,RC_GH200"` 定数を追加
    - `is_estimate_target` 関数: システムが `ESTIMATE_SYSTEMS` に含まれるか判定
    - `has_estimate_script` 関数: `$1/estimate.sh` が存在するか判定
    - `emit_estimate_job` 関数: estimate ジョブのYAMLブロックを出力（tags: general, needs: send_results, script: bash scripts/run_estimate.sh）
    - `emit_send_estimate_job` 関数: send_estimate ジョブのYAMLブロックを出力（tags: fncx-curl-jq, needs: estimate, script: bash scripts/send_estimate.sh）
    - YAML生成ルール準拠: scriptセクションはシンプルに
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

- [x] 7. matrix_generate.sh への推定ステージ統合
  - [x] 7.1 `scripts/matrix_generate.sh` にestimate/send_estimateステージと推定ジョブ生成ロジックを追加する
    - stagesに `estimate` と `send_estimate` を追加
    - 既存の `emit_send_results_job` 呼び出し直後に、`has_estimate_script` && `is_estimate_target` の条件で `emit_estimate_job` と `emit_send_estimate_job` を呼び出す
    - cross/native両モードで同様の処理を追加
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 7.2 Property 5: 推定ジョブ生成の条件判定テスト
    - **Property 5: 推定ジョブ生成の条件判定**
    - hypothesisでプログラム名とシステム名の組み合わせを生成し、estimate.shの有無とシステムがESTIMATE_SYSTEMSに含まれるかの条件で、生成YAMLに推定ジョブが含まれる/含まれないことを検証
    - **Validates: Requirements 2.7, 4.4, 4.5**

  - [ ]* 7.3 Property 6: 生成YAMLの構造正当性テスト
    - **Property 6: 生成YAMLの構造正当性**
    - 推定対象の組み合わせで生成されたYAMLをパースし、estimateステージとsend_estimateステージの存在、needsの依存関係が正しいことを検証
    - **Validates: Requirements 4.1, 4.2, 4.3**

- [x] 8. チェックポイント - YAML生成の動作確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問してください。

- [x] 9. .gitlab-ci.yml の変更とUUID推定モード
  - [x] 9.1 `.gitlab-ci.yml` に `estimate_uuid` 変数と推定モード用ジョブを追加する
    - variables に `estimate_uuid: ""` を追加
    - `generate_estimate_matrix` ジョブ: `estimate_uuid != ""` の場合のみ実行、`bash scripts/generate_estimate_from_uuid.sh` を呼び出し
    - `trigger_estimate_pipeline` ジョブ: 生成されたYAMLで子パイプラインをトリガー
    - 既存の `generate_matrix` と `trigger_child_pipeline` のrulesに `estimate_uuid != ""` → `when: never` を追加
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 9.2 `scripts/generate_estimate_from_uuid.sh` を作成する
    - `estimate_uuid` と `code` の両方が指定されていることを確認（未指定時はエラー終了）
    - fetch → estimate → send_estimate の3ステージYAMLを `.gitlab-ci.estimate.yml` に生成
    - YAML生成ルール準拠: scriptセクションはシンプルに
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 9.3 `scripts/fetch_result_by_uuid.sh` を作成する
    - `estimate_uuid` と `code` の両方が設定されていることを確認（未設定時はエラー終了）
    - Result_Serverから指定UUIDのResult_JSONを取得し `results/result0.json` に保存
    - _Requirements: 8.2, 8.5_

- [x] 10. Estimate_JSON と result_server の互換性テスト
  - [ ]* 10.1 Property 4: Estimate_JSON ↔ result_server 互換性テスト
    - **Property 4: Estimate_JSON と result_server の互換性**
    - hypothesisで有効なEstimate_JSONを生成し、一時ファイルに書き出し
    - `load_estimated_results_table` で読み込んだ結果の行が、元のJSONの各フィールド（code, exp, benchmark_system, benchmark_fom, benchmark_nodes, systemA_*, systemB_*, performance_ratio）と一致することを検証
    - Python直接テスト（subprocess不要）
    - **Validates: Requirements 5.5**

- [x] 11. 最終チェックポイント - 全テスト通過確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問してください。

## 備考

- `*` マーク付きタスクはオプショナルで、MVP実装時にはスキップ可能
- 各タスクは対応する要件番号を参照しており、トレーサビリティを確保
- プロパティテストは対応する実装タスクの直後に配置し、早期にバグを検出
- シェルスクリプトのテストはPython hypothesis + subprocess で実施
- Property 4（result_server互換性）のみPython直接テスト
