# Implementation Plan: Pipeline Timing

## Overview

BenchKitのCIパイプラインにbuild時間・queue時間・run時間の計測機能を追加し、実行モード（cross/native）およびCIトリガー種別をResult_JSONに記録・表示する。変更は3層（シェルスクリプト → Result_JSON → result_server）にまたがり、各タスクは前のタスクの成果物に依存する。

## Tasks

- [x] 1. タイミング収集スクリプトの作成
  - [x] 1.1 `scripts/collect_timing.sh` を新規作成する
    - `results/build_start`, `results/build_end`, `results/run_start`, `results/run_end`, `results/queue_submit` ファイルからタイムスタンプを読み取る
    - `build_time = build_end - build_start`, `run_time = run_end - run_start`, `queue_time = run_start - queue_submit` を計算する
    - 結果を `results/timing.env` に `KEY=VALUE` 形式で出力する
    - タイムスタンプファイルが存在しない場合は該当フィールドを0として記録する
    - LF改行を使用すること
    - _Requirements: 1.5, 1.6, 2.5_

- [x] 2. matrix_generate.sh にタイミング計測コマンドを埋め込む
  - [x] 2.1 crossモードのbuildジョブにビルド開始・終了時刻記録コマンドを追加する
    - `date +%s > results/build_start` をbuild.sh実行前に追加
    - `date +%s > results/build_end` をbuild.sh実行後に追加
    - YAMLルール（シンプルなコマンドのみ、リダイレクト禁止）に従い、`date` の出力をファイルに書き込む方法として `bash -c` または別スクリプト呼び出しを使用する
    - _Requirements: 1.1_
  - [x] 2.2 crossモードのrunジョブにタイミング計測コマンドを追加する
    - `results/queue_submit` をスクリプトセクション冒頭で記録
    - `results/run_start` をrun.sh実行直前に記録
    - `results/run_end` をrun.sh実行後に記録
    - `bash scripts/collect_timing.sh` を呼び出す
    - result.shの呼び出しに第3引数 `cross` を追加する
    - _Requirements: 1.2, 1.4, 3.1_
  - [x] 2.3 nativeモードのbuild_runジョブにタイミング計測コマンドを追加する
    - `results/queue_submit` をスクリプトセクション冒頭で記録
    - `results/build_start`, `results/build_end` をbuild.sh前後に記録
    - `results/run_start`, `results/run_end` をrun.sh前後に記録
    - `bash scripts/collect_timing.sh` を呼び出す
    - result.shの呼び出しに第3引数 `native` を追加する
    - _Requirements: 1.3, 1.4, 3.1_

- [x] 3. result.sh に新フィールド出力を追加する
  - [x] 3.1 第3引数 `execution_mode` の受け取りを追加する
    - `execution_mode=$3` として受け取る
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 3.2 `write_result_json` 関数に `pipeline_timing` ブロックを追加する
    - `results/timing.env` が存在する場合のみ `source` で読み込む
    - `pipeline_timing` オブジェクト（build_time, queue_time, run_time）をJSON出力に追加する
    - `results/timing.env` が存在しない場合は `pipeline_timing` フィールドを省略する
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 3.3 `write_result_json` 関数に `execution_mode` と `ci_trigger` フィールドを追加する
    - `execution_mode` が空でない場合のみフィールドを追加する
    - `ci_trigger` は `$CI_PIPELINE_SOURCE` から取得し、未定義の場合は `"unknown"` を使用する
    - _Requirements: 3.2, 3.3, 4.1, 4.2, 4.3, 4.4_

- [x] 4. チェックポイント - シェルスクリプト層の確認
  - シェルスクリプトの構文確認を行い、ユーザーに質問があれば確認する。

- [x] 5. results_loader.py に新フィールドの読み取りを追加する
  - [x] 5.1 `_build_row` 関数に新フィールドの抽出ロジックを追加する
    - `pipeline_timing` オブジェクトから `build_time`, `queue_time`, `run_time` を取得する
    - `execution_mode` フィールドを取得する
    - `ci_trigger` フィールドを取得する
    - フィールドが存在しない場合は `"-"` をフォールバック値として使用する
    - `pipeline_timing` が `dict` でない場合も `"-"` をフォールバックする
    - _Requirements: 5.1, 5.3, 6.1, 6.3, 7.1, 7.3, 8.1, 8.2, 8.3, 8.4_
  - [x] 5.2 `columns` リストに新カラムを追加する
    - `("Mode", "execution_mode")`, `("Trigger", "ci_trigger")`, `("Build Time", "build_time")`, `("Queue Time", "queue_time")`, `("Run Time", "run_time")` を追加する
    - _Requirements: 5.2, 6.2, 7.2_
  - [ ]* 5.3 Property 1 のプロパティベーステストを作成する
    - **Property 1: 新フィールドの抽出とフォールバック**
    - hypothesisを使用し、`pipeline_timing`/`execution_mode`/`ci_trigger` の有無をランダムに生成したResult_JSONデータに対して、`_build_row` が常に新フィールドキーを含む行データを返し、存在しない場合は `"-"` をフォールバックすることを検証する
    - 最低100イテレーション実行する
    - **Validates: Requirements 5.1, 5.3, 6.1, 6.3, 7.1, 7.3, 8.1, 8.2, 8.3, 8.4**

- [x] 6. _results_table.html に新カラムを追加する
  - [x] 6.1 テーブルヘッダーとボディに新カラムを追加する
    - `thead` の表示条件リスト（`col_name in [...]`）に `"Mode"`, `"Trigger"`, `"Build Time"`, `"Queue Time"`, `"Run Time"` を追加する
    - `tbody` の表示条件リスト（`key in [...]`）に `"execution_mode"`, `"ci_trigger"`, `"build_time"`, `"queue_time"`, `"run_time"` を追加する
    - 各新カラムにツールチップを追加する
    - _Requirements: 5.2, 5.4, 6.2, 7.2_

- [x] 7. 既存テストの更新と新規テストの追加
  - [x] 7.1 `test_results_loader.py` の既存テスト `test_existing_columns_unchanged` を新カラムを含むように更新する
    - 新カラム（Mode, Trigger, Build Time, Queue Time, Run Time）を `expected_columns` に追加する
    - _Requirements: 5.2, 6.2, 7.2_
  - [x] 7.2 新フィールド付きResult_JSONの行構築テストを追加する
    - `pipeline_timing`, `execution_mode`, `ci_trigger` を含むResult_JSONから正しく行データが構築されることを確認する
    - _Requirements: 5.1, 6.1, 7.1_
  - [x] 7.3 新フィールドなしResult_JSONの後方互換性テストを追加する
    - 既存形式のResult_JSONでもエラーなく行データが構築され、フォールバック値 `"-"` が返ることを確認する
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 8. 最終チェックポイント - 全テスト実行
  - 全テストが通ることを確認し、ユーザーに質問があれば確認する。

## Notes

- タスク `*` マーク付きはオプションでスキップ可能
- 各タスクは特定の要件にトレースされている
- チェックポイントでインクリメンタルに検証を行う
- Property 1 は `_build_row` 関数の新フィールド抽出とフォールバック動作を検証する
- シェルスクリプトはLF改行必須
- YAML生成時はワークスペースルール（yaml-generation.md）に従い、シンプルなコマンドのみ使用する
- テンプレートのユーザー向けテキスト（カラム名、ツールチップ等）は英語で記述する
