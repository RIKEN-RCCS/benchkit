# Implementation Plan: パイプラインスクリプトのリファクタリング

## Overview

BenchKit の CI/CD パイプライン生成スクリプト群のリファクタリング。CSV パース・フィルタリングの共通化、YAML 生成パターンの共通化、不要スクリプト除去、case 文統合、BenchPark ジョブ定義の重複排除、未使用関数整理を段階的に実施する。各ステップでリファクタリング前後の出力等価性を diff で検証する。

## Tasks

- [x] 1. リファクタリング前の出力を保存（ベースライン取得）
  - `bash ./scripts/matrix_generate.sh` を実行し `.gitlab-ci.generated.yml` を `.gitlab-ci.generated.yml.before` としてコピー
  - `bash ./benchpark-bridge/scripts/ci_generator.sh` を実行し `.gitlab-ci.benchpark.yml` を `.gitlab-ci.benchpark.yml.before` としてコピー
  - これらのベースラインファイルは以降の各ステップで diff 比較に使用する
  - _Requirements: 1.4, 2.4, 4.4, 6.5_

- [x] 2. CSV 読み込みとフィルタリングの共通関数を job_functions.sh に追加
  - [x] 2.1 `parse_list_csv_line()` を job_functions.sh に追加
    - 7フィールド（system, mode, queue_group, nodes, numproc_node, nthreads, elapse）を受け取り、空白トリム・ヘッダースキップ・コメント行スキップを行い、`csv_system` 等の変数にエクスポートする
    - _Requirements: 1.1, 1.3, 1.4_
  - [x] 2.2 `parse_apps_csv_line()` を job_functions.sh に追加
    - 3フィールド（system, app, description）を受け取り、同様のパース処理を行う
    - _Requirements: 1.1, 1.4_
  - [x] 2.3 `match_filter()` を job_functions.sh に追加
    - カンマ区切りフィルタ文字列と対象値を受け取り、マッチ判定を返す。フィルタが空なら常にマッチ
    - _Requirements: 2.1, 2.3, 2.4_

- [x] 3. matrix_generate.sh を共通関数に移行
  - [x] 3.1 CSV パース部分を `parse_list_csv_line()` 呼び出しに置換
    - `while IFS=, read -r ...` ループ内の空白トリム・ヘッダースキップ・コメント行スキップを `parse_list_csv_line` 呼び出しに置換し、変数参照を `csv_system` 等に更新
    - _Requirements: 1.2, 1.4_
  - [x] 3.2 フィルタ部分を `match_filter()` 呼び出しに置換
    - system フィルタと code フィルタの IFS/read/for ループを `match_filter "$SYSTEM_FILTER" "$csv_system"` と `match_filter "$CODE_FILTER" "$program"` に置換
    - _Requirements: 2.2, 2.4_
  - [x] 3.3 diff で出力等価性を検証
    - `bash ./scripts/matrix_generate.sh` を実行し `.gitlab-ci.generated.yml.before` と diff 比較して差分がないことを確認
    - _Requirements: 1.4, 2.4_

- [x] 4. Checkpoint - matrix_generate.sh の出力等価性確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. YAML 生成共通関数を job_functions.sh に追加し matrix_generate.sh に適用
  - [x] 5.1 `emit_send_results_job()`, `emit_artifacts_block()`, `emit_id_tokens_block()` を job_functions.sh に追加
    - デザインドキュメントの仕様に従い、send_results ジョブ・artifacts ブロック・id_tokens ブロックの YAML 出力関数を追加
    - _Requirements: 4.1, 4.2_
  - [x] 5.2 matrix_generate.sh の cross/native 両モードで send_results ジョブ出力を `emit_send_results_job()` 呼び出しに置換
    - cross モードの `${job_prefix}_send_results:` ブロックと native モードの `${job_prefix}_send_results:` ブロックを関数呼び出しに置換
    - _Requirements: 4.3, 4.4_
  - [x] 5.3 diff で出力等価性を検証
    - `bash ./scripts/matrix_generate.sh` を実行し `.gitlab-ci.generated.yml.before` と diff 比較して差分がないことを確認
    - _Requirements: 4.4_

- [x] 6. Checkpoint - YAML 共通関数適用後の出力等価性確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. test_submit.sh の case 文統合
  - [x] 7.1 if 文連鎖を case 文に統合
    - Fugaku/FugakuCN, RC_GH200, MiyabiC, MiyabiG の4つの if ブロックを単一の case 文に統合。各 case ブロック内のコマンドは既存と完全に同一とする
    - _Requirements: 5.1, 5.3_
  - [x] 7.2 未知システムのエラーハンドリングを追加
    - `*)` パターンで `echo "Error: Unknown system '$system'"` とサポートシステム一覧を出力し `exit 1` する
    - _Requirements: 5.2_

- [x] 8. 不要スクリプトの除去
  - [x] 8.1 `scripts/debug_job.sh`, `scripts/run_benchmark.sh`, `scripts/check_results.sh` を削除
    - _Requirements: 3.1_
  - [x] 8.2 README.md のファイル一覧から削除した3ファイルの記述を除去
    - `scripts/` セクションの `run_benchmark.sh`, `check_results.sh`, `debug_job.sh` の行を削除
    - _Requirements: 3.1, 3.2_

- [x] 9. Checkpoint - 不要スクリプト除去後の動作確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. ci_generator.sh の共通関数移行と重複排除
  - [x] 10.1 CSV パース部分を `parse_apps_csv_line()` 呼び出しに置換
    - ci_generator.sh の while ループ内の空白トリム・ヘッダースキップ・コメント行スキップを `parse_apps_csv_line` 呼び出しに置換。`source ./scripts/job_functions.sh` を追加
    - _Requirements: 1.2, 1.4_
  - [x] 10.2 フィルタ部分を `match_filter()` 呼び出しに置換
    - system フィルタと app フィルタの IFS/read/for ループを `match_filter` 呼び出しに置換
    - _Requirements: 2.2, 2.4_
  - [x] 10.3 `emit_convert_job()` と `emit_send_job()` を ci_generator.sh 内に追加
    - SEND_ONLY モードと通常モードで重複する convert ジョブと send ジョブの YAML 定義を関数化
    - _Requirements: 6.1, 6.2_
  - [x] 10.4 SEND_ONLY モードと通常モードの分岐を関数呼び出しに置換
    - 両モードの convert/send ブロックを `emit_convert_job` / `emit_send_job` 呼び出しに置換。通常モードの setup/run はそのまま維持
    - _Requirements: 6.3, 6.4_
  - [x] 10.5 diff で出力等価性を検証
    - `bash ./benchpark-bridge/scripts/ci_generator.sh` を実行し `.gitlab-ci.benchpark.yml.before` と diff 比較して差分がないことを確認
    - _Requirements: 6.5_

- [x] 11. Checkpoint - ci_generator.sh の出力等価性確認
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. BenchPark common.sh の未使用関数整理
  - [x] 12.1 未使用の5関数に TODO コメントを付与
    - `get_benchpark_installation_path`, `get_benchpark_workspace`, `get_benchpark_experiment_path`, `get_benchpark_system_path`, `get_benchpark_results_dir` の各関数定義の直前に `# TODO: 現在未使用。将来のシステム拡張時に使用予定` コメントを追加
    - _Requirements: 7.1, 7.2_

- [x] 13. Final checkpoint - 全体の動作確認
  - Ensure all tests pass, ask the user if questions arise.
  - `bash ./scripts/matrix_generate.sh` の出力が `.gitlab-ci.generated.yml.before` と一致すること
  - `bash ./benchpark-bridge/scripts/ci_generator.sh` の出力が `.gitlab-ci.benchpark.yml.before` と一致すること

## Notes

- テストファイルの新規作成は不要。検証はリファクタリング前後の出力比較（diff）で行う
- シェルスクリプトのリファクタリングのため PBT は使用しない
- 各チェックポイントで出力等価性を確認し、差分があれば修正してから次に進む
- `programs/*/build.sh`, `run.sh` および `result_server/` は対象外
