# 実装計画: Estimate_JSON スキーマ再設計

## 概要

Result_JSON と Estimate_JSON のスキーマ再設計を、依存関係の順序に従って段階的に実装する。まず result.sh のパーサー拡張とハードウェア情報削除、次に API 拡張、estimate_common.sh の更新、qws スクリプトの対応、最後に result_server 側（ローダー・テンプレート・フィルタ）の更新を行う。

## タスク

- [x] 1. result.sh の SECTION/OVERLAP パーサー追加とハードウェア情報削除
  - [x] 1.1 result.sh から `case "$system"` ハードウェア情報生成ブロックを削除する
    - `cpu_name`, `gpu_name`, `cpu_cores`, `cpus_per_node`, `gpus_per_node` の case 文による設定を削除
    - `uname_info` 変数の生成と使用を削除
    - Result_JSON 出力から `cpu_name`, `gpu_name`, `cpu_cores`, `cpus_per_node`, `gpus_per_node`, `uname` フィールドを削除
    - _要件: 12.1, 12.2, 12.3, 12.4_

  - [x] 1.2 result.sh に `numproc_node` パーサーを追加する
    - FOM 行から `numproc_node:値` を抽出するパース処理を追加
    - Result_JSON 出力に `numproc_node` フィールドを追加
    - _要件: 10.6, 11.6_

  - [x] 1.3 result.sh に SECTION/OVERLAP パーサーを実装する
    - FOM 行の後に続く `SECTION:区間名 time:秒` 形式の行をパースする処理を追加
    - `OVERLAP:区間A,区間B time:秒` 形式の行をパースする処理を追加
    - OVERLAP 行の区間名が同一ブロック内の SECTION で未定義の場合、stderr にエラーを出力
    - パースした区間とオーバーラップを `fom_breakdown` オブジェクトとして Result_JSON に格納
    - SECTION/OVERLAP 行が存在しない FOM ブロックでは `fom_breakdown` を省略
    - `jq` による JSON 検証を維持
    - _要件: 10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.2, 11.3, 11.4, 11.5, 11.7, 12.5_

  - [ ]* 1.4 result.sh のパーサーのユニットテストを作成する
    - SECTION/OVERLAP ありの results/result ファイルで正しい fom_breakdown が生成されることを検証
    - SECTION/OVERLAP なしの場合に fom_breakdown が省略されることを検証
    - OVERLAP の区間名が未定義の場合にエラーが stderr に出力されることを検証
    - numproc_node のパースを検証
    - ハードウェア情報フィールドが出力されないことを検証
    - _要件: 10.1-10.6, 11.1-11.7, 12.1-12.5_

- [x] 2. programs/qws/run.sh に numproc_node と仮 SECTION/OVERLAP 出力を追加
  - [x] 2.1 qws/run.sh の各 case ブランチの FOM 行に `numproc_node:$numproc_node` を追加する
    - 各 system case で適切な numproc_node 値を設定（例: MPI プロセス数）
    - _要件: 14.4_

  - [x] 2.2 qws/run.sh の各 case ブランチに仮の SECTION/OVERLAP 行を追加する
    - FOM 行の後に `SECTION:compute_kernel time:0.30` 等の固定値 SECTION 行を出力
    - `OVERLAP:compute_kernel,communication time:0.05` 等の固定値 OVERLAP 行を出力
    - _要件: 14.1, 14.2, 14.3_

- [x] 3. チェックポイント — result.sh と qws/run.sh の変更確認
  - テストがあれば実行し、全テストがパスすることを確認する。疑問があればユーザーに確認する。

- [x] 4. query_result API に `_meta` を追加
  - [x] 4.1 `result_server/routes/api.py` の `query_result` 関数にファイル名からの timestamp/uuid 抽出と `_meta` オブジェクト追加を実装する
    - ファイル名から `YYYYMMDD_HHMMSS` パターンで timestamp を抽出し `YYYY-MM-DD HH:MM:SS` 形式に変換
    - ファイル名から UUID を抽出
    - `data["_meta"] = {"timestamp": timestamp, "uuid": uid}` をレスポンスに追加
    - 既存のレスポンスフィールド（code, system, FOM 等）は変更しない
    - _要件: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 4.2 `result_server/tests/test_api_routes.py` に `_meta` のテストを追加する
    - query_result レスポンスに `_meta.timestamp` と `_meta.uuid` が含まれることを検証
    - ファイル名に timestamp/uuid がない場合の動作を検証
    - _要件: 5.1, 5.2, 5.3_

- [x] 5. estimate_common.sh の更新（変数リネーム・新変数・関数拡張）
  - [x] 5.1 estimate_common.sh のグローバル変数を更新する
    - `est_benchmark_system`, `est_benchmark_fom`, `est_benchmark_nodes` を廃止
    - `est_current_nodes` → `est_current_target_nodes`、`est_current_method` → `est_current_scaling_method` にリネーム
    - `est_future_nodes` → `est_future_target_nodes`、`est_future_method` → `est_future_scaling_method` にリネーム
    - current_system 用ベンチマーク変数を追加: `est_current_bench_system`, `est_current_bench_fom`, `est_current_bench_nodes`, `est_current_bench_numproc_node`, `est_current_bench_timestamp`, `est_current_bench_uuid`
    - future_system 用ベンチマーク変数を追加: `est_future_bench_system`, `est_future_bench_fom`, `est_future_bench_nodes`, `est_future_bench_numproc_node`, `est_future_bench_timestamp`, `est_future_bench_uuid`
    - fom_breakdown 変数を追加: `est_current_fom_breakdown`, `est_future_fom_breakdown`
    - _要件: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 5.2 estimate_common.sh の `read_values` 関数を拡張する
    - `numproc_node` フィールドを読み取り `est_numproc_node` に格納
    - `timestamp` フィールドを読み取り `est_timestamp` に格納（存在しない場合は空文字列）
    - `uuid` フィールドを読み取り `est_uuid` に格納（存在しない場合は空文字列）
    - _要件: 3.1, 3.2, 3.3_

  - [x] 5.3 estimate_common.sh の `fetch_current_fom` 関数を拡張する
    - API レスポンスから `node_count` を読み取り `est_current_bench_nodes` に格納
    - API レスポンスから `numproc_node` を読み取り `est_current_bench_numproc_node` に格納
    - API レスポンスから `_meta.timestamp` を読み取り `est_current_bench_timestamp` に格納
    - API レスポンスから `_meta.uuid` を読み取り `est_current_bench_uuid` に格納
    - `est_current_bench_system` に検索対象のシステム名を格納
    - `est_current_bench_fom` に取得した FOM 値を格納
    - _要件: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 5.4 estimate_common.sh の `print_json` 関数を新スキーマに更新する
    - トップレベルの `benchmark_system`, `benchmark_fom`, `benchmark_nodes` を廃止
    - `current_system` と `future_system` にそれぞれ `benchmark` サブオブジェクトを出力
    - `nodes` → `target_nodes`、`method` → `scaling_method` にリネーム
    - `fom_breakdown` が設定されている場合のみ条件付きで出力
    - _要件: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.6, 13.5, 13.6_

- [x] 6. programs/qws/estimate.sh を新スキーマに対応させる
  - [x] 6.1 qws/estimate.sh の変数代入を新スキーマに移行する
    - `est_benchmark_system`, `est_benchmark_fom`, `est_benchmark_nodes` への代入を廃止
    - future_system 用ベンチマーク変数（`est_future_bench_system`, `est_future_bench_fom`, `est_future_bench_nodes`, `est_future_bench_numproc_node`, `est_future_bench_timestamp`, `est_future_bench_uuid`）を設定
    - `est_current_nodes` → `est_current_target_nodes`、`est_current_method` → `est_current_scaling_method` に変更
    - `est_future_nodes` → `est_future_target_nodes`、`est_future_method` → `est_future_scaling_method` に変更
    - `est_current_fom_breakdown` と `est_future_fom_breakdown` を設定（fom_breakdown のパススルー）
    - _要件: 6.1, 6.2, 6.3, 6.4, 13.1, 13.2_

- [x] 7. チェックポイント — シェルスクリプト変更の確認
  - 全テストがパスすることを確認する。疑問があればユーザーに確認する。

- [x] 8. results_loader の新スキーマ対応
  - [x] 8.1 `result_server/utils/results_loader.py` の `ESTIMATED_FIELD_MAP` と `_matches_filters` を更新する
    - `ESTIMATED_FIELD_MAP` の `system` キーを新スキーマのフィールドパスに更新
    - `_matches_filters` でネストされたフィールドパス（`current_system.system`）をサポート
    - `code` と `exp` のフィルタリングは引き続きトップレベルフィールドで行う
    - _要件: 9.1, 9.2, 9.3_

  - [x] 8.2 `result_server/utils/results_loader.py` の `load_estimated_results_table` を新スキーマに対応させる
    - `current_system.benchmark` からベンチマーク元情報（system, fom, nodes）を読み取る
    - `current_system.target_nodes`, `current_system.scaling_method` を読み取る
    - `future_system.benchmark`, `future_system.target_nodes`, `future_system.scaling_method` を同様に読み取る
    - 行データに `systemA_target_nodes`, `systemA_scaling_method`, `systemA_bench_system`, `systemA_bench_fom`, `systemA_bench_nodes` を追加
    - 行データに `systemB_target_nodes`, `systemB_scaling_method`, `systemB_bench_system`, `systemB_bench_fom`, `systemB_bench_nodes` を追加
    - 旧スキーマの `benchmark_system`, `benchmark_fom`, `benchmark_nodes` 行データを廃止
    - _要件: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [ ]* 8.3 `result_server/tests/test_results_loader.py` に新スキーマのテストを追加する
    - 新スキーマの Estimate_JSON を読み込み、行データに正しいフィールドが含まれることを検証
    - `_matches_filters` がネストされたフィールドパスで正しくフィルタリングすることを検証
    - _要件: 7.1-7.8, 9.1-9.3_

- [x] 9. estimated_results.html テンプレートの更新
  - [x] 9.1 `result_server/templates/estimated_results.html` のテーブルヘッダーとボディを新スキーマに対応させる
    - 旧スキーマのトップレベル Benchmark カラム（Benchmark System, Benchmark FOM, Benchmark Nodes）を廃止
    - System A グループに Target Nodes, Scaling Method, Bench System, Bench FOM, Bench Nodes カラムを追加
    - System B グループに Target Nodes, Scaling Method, Bench System, Bench FOM, Bench Nodes カラムを追加
    - 2段ヘッダー構成（System A / System B のグループヘッダーと個別カラムヘッダー）を実装
    - テーブルボディの変数参照を新しい行データフィールドに更新
    - _要件: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 10. チェックポイント — result_server 側の変更確認
  - 全テストがパスすることを確認する。疑問があればユーザーに確認する。

## 備考

- `*` マーク付きのタスクはオプションであり、MVP では省略可能
- 各タスクは特定の要件を参照しており、トレーサビリティを確保している
- チェックポイントで段階的に検証を行い、問題を早期に発見する
- プロパティテストは Result_JSON / Estimate_JSON のスキーマ検証に有効だが、シェルスクリプト中心の実装のため、Python テスト側で検証する
- シェルスクリプトは LF 改行コードを使用すること
- `set -euo pipefail` 環境では curl 失敗時に `set +e` / `set -e` でラップすること
