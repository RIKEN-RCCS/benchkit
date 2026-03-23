# 要件ドキュメント

## はじめに

Estimate_JSON（性能推定結果のJSONスキーマ）を再設計する。現行スキーマではベンチマーク元データがトップレベルに1つだけ存在し、current_system と future_system で共有されている。新スキーマでは、各システムが独自のベンチマーク元データ（system, fom, nodes, numproc_node, timestamp, uuid）、ターゲットノード数、スケーリング方法を保持する構造に変更する。これにより、current_system と future_system が異なるベンチマーク元データに基づく推定を表現できるようになる。

さらに、FOM分解（fom_breakdown）をサポートする。FOMは複数の計算区間・通信区間の合計からオーバーラップ時間を差し引いて算出される。各区間を個別にスケーリング・推定するため、Result_JSON と Estimate_JSON の両方に `fom_breakdown` 構造を追加する。また、result.sh のハードウェア情報生成を廃止し、system_info.csv への一本化を行う。

## 用語集

- **Estimate_JSON**: 性能推定結果を格納するJSONファイル。`result_server` の `ESTIMATED_DIR` に保存される
- **Result_JSON**: ベンチマーク実行結果を格納するJSONファイル。`result_server` の `RECEIVED_DIR` に保存される
- **estimate_common.sh**: 性能推定スクリプト共通ライブラリ（`scripts/estimate_common.sh`）
- **estimate.sh**: アプリケーション固有の推定スクリプト（例: `programs/qws/estimate.sh`）
- **results_loader**: 結果JSONを読み込みテーブル行に変換するPythonモジュール（`result_server/utils/results_loader.py`）
- **estimated_results_page**: 推定結果一覧を表示するHTMLテンプレート（`result_server/templates/estimated_results.html`）
- **query_result_api**: 結果を検索するAPI（`/api/query/result`）
- **benchmark サブオブジェクト**: current_system / future_system 内に含まれるベンチマーク元データの構造体。system, fom, nodes, numproc_node, timestamp, uuid フィールドを持つ
- **target_nodes**: プロダクションラン（大規模実行）のターゲットノード数
- **scaling_method**: ベンチマーク結果からターゲットノード数へのスケーリング手法（例: measured, perf-counter-analysis, scale-mock）
- **ESTIMATED_FIELD_MAP**: results_loader 内で推定結果JSONのフィールド名をマッピングする定数
- **fom_breakdown**: FOMを構成する計算区間・通信区間・オーバーラップの内訳を表すオブジェクト。`sections`（区間リスト）と `overlaps`（オーバーラップリスト）を持つ
- **SECTION行**: `results/result` ファイル内でFOM構成区間を記述する行。`SECTION:区間名 time:秒` 形式
- **OVERLAP行**: `results/result` ファイル内でオーバーラップ時間を記述する行。`OVERLAP:区間A,区間B time:秒` 形式
- **result.sh**: ベンチマーク実行結果（`results/result`）をパースしてResult_JSONを生成するシェルスクリプト（`scripts/result.sh`）
- **numproc_node**: ノードあたりのMPIプロセス数。run.sh の引数として利用可能
- **system_info.csv**: システムのハードウェア情報を一元管理するCSVファイル（`config/system_info.csv`）。system_info.py から読み込まれる

## 要件

### 要件 1: Estimate_JSON スキーマの再設計

**ユーザーストーリー:** 開発者として、current_system と future_system がそれぞれ独立したベンチマーク元データを持つEstimate_JSONスキーマを使いたい。これにより、異なるベンチマーク元データに基づく推定を正確に表現できる。

#### 受け入れ基準

1. THE Estimate_JSON SHALL トップレベルに `code`、`exp`、`current_system`、`future_system`、`performance_ratio` フィールドを持つ
2. THE Estimate_JSON SHALL トップレベルの `benchmark_system`、`benchmark_fom`、`benchmark_nodes` フィールドを含まない
3. THE Estimate_JSON の `current_system` オブジェクト SHALL `system`、`fom`、`target_nodes`、`scaling_method`、`benchmark` フィールドを持つ
4. THE Estimate_JSON の `future_system` オブジェクト SHALL `system`、`fom`、`target_nodes`、`scaling_method`、`benchmark` フィールドを持つ
5. THE Estimate_JSON の `benchmark` サブオブジェクト SHALL `system`、`fom`、`nodes`、`numproc_node`、`timestamp`、`uuid` フィールドを持つ
6. THE Estimate_JSON SHALL 旧スキーマの `current_system.nodes` フィールドを `target_nodes` にリネームする
7. THE Estimate_JSON SHALL 旧スキーマの `current_system.method` フィールドを `scaling_method` にリネームする
8. THE Estimate_JSON SHALL 旧スキーマの `future_system.nodes` フィールドを `target_nodes` にリネームする
9. THE Estimate_JSON SHALL 旧スキーマの `future_system.method` フィールドを `scaling_method` にリネームする

### 要件 2: estimate_common.sh の print_json 関数の更新

**ユーザーストーリー:** 開発者として、print_json 関数が新スキーマに準拠したJSONを出力するようにしたい。これにより、推定スクリプトが正しい形式のEstimate_JSONを生成できる。

#### 受け入れ基準

1. THE estimate_common.sh SHALL `est_benchmark_system`、`est_benchmark_fom`、`est_benchmark_nodes` グローバル変数を廃止する
2. THE estimate_common.sh SHALL `est_current_nodes`、`est_current_method` グローバル変数をそれぞれ `est_current_target_nodes`、`est_current_scaling_method` にリネームする
3. THE estimate_common.sh SHALL `est_future_nodes`、`est_future_method` グローバル変数をそれぞれ `est_future_target_nodes`、`est_future_scaling_method` にリネームする
4. THE estimate_common.sh SHALL current_system 用のベンチマーク元データ変数（`est_current_bench_system`、`est_current_bench_fom`、`est_current_bench_nodes`、`est_current_bench_numproc_node`、`est_current_bench_timestamp`、`est_current_bench_uuid`）を新たに定義する
5. THE estimate_common.sh SHALL future_system 用のベンチマーク元データ変数（`est_future_bench_system`、`est_future_bench_fom`、`est_future_bench_nodes`、`est_future_bench_numproc_node`、`est_future_bench_timestamp`、`est_future_bench_uuid`）を新たに定義する
6. THE print_json 関数 SHALL 新スキーマに準拠したJSON（current_system.benchmark、future_system.benchmark を含む）を出力する

### 要件 3: estimate_common.sh の read_values 関数の更新

**ユーザーストーリー:** 開発者として、read_values 関数がResult_JSONからベンチマーク元データのメタ情報（numproc_node 等）も読み取れるようにしたい。

#### 受け入れ基準

1. THE read_values 関数 SHALL Result_JSON から `numproc_node` フィールドを読み取り `est_numproc_node` 変数に格納する
2. THE read_values 関数 SHALL Result_JSON から `timestamp` フィールドを読み取り `est_timestamp` 変数に格納する（フィールドが存在しない場合は空文字列を設定する）
3. THE read_values 関数 SHALL Result_JSON から `uuid` フィールドを読み取り `est_uuid` 変数に格納する（フィールドが存在しない場合は空文字列を設定する）

### 要件 4: estimate_common.sh の fetch_current_fom 関数の拡張

**ユーザーストーリー:** 開発者として、fetch_current_fom 関数がFOM値だけでなくベンチマーク元データのメタ情報（nodes, numproc_node, timestamp, uuid）も取得するようにしたい。

#### 受け入れ基準

1. THE fetch_current_fom 関数 SHALL APIレスポンスから `node_count` を読み取り `est_current_bench_nodes` に格納する
2. THE fetch_current_fom 関数 SHALL APIレスポンスから `numproc_node` を読み取り `est_current_bench_numproc_node` に格納する
3. THE fetch_current_fom 関数 SHALL APIレスポンスから timestamp 情報を読み取り `est_current_bench_timestamp` に格納する
4. THE fetch_current_fom 関数 SHALL APIレスポンスから uuid 情報を読み取り `est_current_bench_uuid` に格納する
5. THE fetch_current_fom 関数 SHALL `est_current_bench_system` に検索対象のシステム名を格納する
6. THE fetch_current_fom 関数 SHALL `est_current_bench_fom` に取得したFOM値を格納する


### 要件 5: query_result_api のレスポンス拡張

**ユーザーストーリー:** 開発者として、`/api/query/result` APIのレスポンスにtimestampとuuid情報が含まれるようにしたい。これにより、fetch_current_fom がベンチマーク元データのメタ情報を取得できる。

#### 受け入れ基準

1. THE query_result_api SHALL レスポンスJSONに `_meta.timestamp` フィールド（ファイル名から抽出した `YYYY-MM-DD HH:MM:SS` 形式）を含める
2. THE query_result_api SHALL レスポンスJSONに `_meta.uuid` フィールド（ファイル名から抽出したUUID）を含める
3. WHEN Result_JSON自体にtimestampやuuidフィールドが存在しない場合、THE query_result_api SHALL ファイル名からこれらの値を抽出して `_meta` に格納する
4. THE query_result_api SHALL 既存のレスポンスフィールド（code, system, FOM 等）を変更しない

### 要件 6: programs/qws/estimate.sh の新スキーマ対応

**ユーザーストーリー:** 開発者として、qws の推定スクリプトが新スキーマに準拠した変数を設定するようにしたい。

#### 受け入れ基準

1. THE estimate.sh SHALL 旧スキーマの `est_benchmark_system`、`est_benchmark_fom`、`est_benchmark_nodes` 変数への代入を廃止する
2. THE estimate.sh SHALL future_system 用のベンチマーク元データ変数（`est_future_bench_system`、`est_future_bench_fom`、`est_future_bench_nodes`、`est_future_bench_numproc_node`、`est_future_bench_timestamp`、`est_future_bench_uuid`）を設定する
3. THE estimate.sh SHALL `est_current_target_nodes` と `est_future_target_nodes` にターゲットノード数を設定する
4. THE estimate.sh SHALL `est_current_scaling_method` と `est_future_scaling_method` にスケーリング方法を設定する

### 要件 7: results_loader の load_estimated_results_table 関数の更新

**ユーザーストーリー:** 開発者として、results_loader が新スキーマのEstimate_JSONを正しく読み込み、テーブル行データに変換するようにしたい。

#### 受け入れ基準

1. THE results_loader SHALL 新スキーマの `current_system.benchmark.system` からベンチマーク元システム名を読み取る
2. THE results_loader SHALL 新スキーマの `current_system.benchmark.fom` からベンチマーク元FOMを読み取る
3. THE results_loader SHALL 新スキーマの `current_system.target_nodes` からターゲットノード数を読み取る
4. THE results_loader SHALL 新スキーマの `current_system.scaling_method` からスケーリング方法を読み取る
5. THE results_loader SHALL 新スキーマの `future_system.benchmark`、`future_system.target_nodes`、`future_system.scaling_method` を同様に読み取る
6. THE results_loader SHALL ESTIMATED_FIELD_MAP を新スキーマに合わせて更新する（`benchmark_system` フィールドの参照を `current_system.benchmark.system` に変更する）
7. THE results_loader SHALL テーブル行データに `systemA_target_nodes`、`systemA_scaling_method`、`systemB_target_nodes`、`systemB_scaling_method` フィールドを含める
8. THE results_loader SHALL テーブル行データに各システムのベンチマーク元情報（`systemA_bench_system`、`systemA_bench_fom`、`systemA_bench_nodes`、`systemB_bench_system`、`systemB_bench_fom`、`systemB_bench_nodes`）を含める

### 要件 8: estimated_results_page テンプレートの更新

**ユーザーストーリー:** 開発者として、推定結果一覧ページが新スキーマのフィールド（target_nodes、scaling_method、各システムのベンチマーク元情報）を表示するようにしたい。

#### 受け入れ基準

1. THE estimated_results_page SHALL System A のカラムに `Target Nodes` と `Scaling Method` を表示する
2. THE estimated_results_page SHALL System B のカラムに `Target Nodes` と `Scaling Method` を表示する
3. THE estimated_results_page SHALL System A の Benchmark 情報（System、FOM、Nodes）を表示する
4. THE estimated_results_page SHALL System B の Benchmark 情報（System、FOM、Nodes）を表示する
5. THE estimated_results_page SHALL 旧スキーマのトップレベル Benchmark カラム（Benchmark System、Benchmark FOM、Benchmark Nodes）を廃止する
6. THE estimated_results_page SHALL テーブルヘッダーを2段構成（System A / System B のグループヘッダーと個別カラムヘッダー）で表示する

### 要件 9: フィルタ機能の新スキーマ対応

**ユーザーストーリー:** 開発者として、推定結果一覧のフィルタ機能が新スキーマでも正しく動作するようにしたい。

#### 受け入れ基準

1. THE results_loader SHALL ESTIMATED_FIELD_MAP の `system` キーを新スキーマのフィールドパスに更新する
2. WHEN system フィルタが指定された場合、THE results_loader SHALL `current_system.system` または `current_system.benchmark.system` を基準にフィルタリングする
3. THE results_loader SHALL `code` と `exp` のフィルタリングを引き続きトップレベルフィールドで行う

### 要件 10: Result_JSON スキーマへの fom_breakdown 追加

**ユーザーストーリー:** 開発者として、Result_JSON にFOMの内訳（計算区間・通信区間・オーバーラップ）を格納できるようにしたい。これにより、FOMの構成要素を個別にスケーリング・分析できる。

#### 受け入れ基準

1. THE Result_JSON SHALL `fom_breakdown` オブジェクトを持つ（存在する場合）
2. THE Result_JSON の `fom_breakdown.sections` SHALL 区間のリストを格納し、各要素は `name`（文字列）と `time`（数値、秒単位）フィールドを持つ
3. THE Result_JSON の `fom_breakdown.overlaps` SHALL オーバーラップのリストを格納し、各要素は `sections`（区間名の配列）と `time`（数値、秒単位）フィールドを持つ
4. THE Result_JSON の `fom_breakdown.sections` の各 `name` SHALL アプリケーション固有の自由な文字列を許容する
5. WHEN SECTION行およびOVERLAP行が `results/result` に存在しない場合、THE Result_JSON SHALL `fom_breakdown` フィールドを省略する
6. THE Result_JSON SHALL `numproc_node` フィールド（ノードあたりのMPIプロセス数、文字列または数値）を持つ

### 要件 11: result.sh の SECTION/OVERLAP パーサー追加

**ユーザーストーリー:** 開発者として、result.sh が `results/result` の SECTION行・OVERLAP行をパースし、Result_JSON の `fom_breakdown` に変換するようにしたい。これにより、アプリ開発者が簡易フォーマットでFOM内訳を記述できる。

#### 受け入れ基準

1. THE result.sh SHALL FOM行の後に続く `SECTION:区間名 time:秒` 形式の行をパースし、区間名と時間を抽出する
2. THE result.sh SHALL FOM行の後に続く `OVERLAP:区間A,区間B time:秒` 形式の行をパースし、区間名リストと時間を抽出する
3. WHEN OVERLAP行の区間名が同一FOMブロック内のSECTION行で定義されていない場合、THE result.sh SHALL エラーメッセージを標準エラー出力に出力する
4. THE result.sh SHALL パースした区間とオーバーラップを Result_JSON の `fom_breakdown` オブジェクトに格納する
5. WHEN SECTION行およびOVERLAP行が存在しない場合、THE result.sh SHALL Result_JSON に `fom_breakdown` フィールドを含めない
6. THE result.sh SHALL `results/result` の `numproc_node:値` をパースし、Result_JSON の `numproc_node` フィールドに格納する
7. THE result.sh SHALL パース結果から有効なJSONを生成する（`jq` による検証を通過する）

### 要件 12: result.sh からハードウェア情報生成の削除

**ユーザーストーリー:** 開発者として、result.sh のハードウェア情報生成を削除し、system_info.csv / system_info.py に一本化したい。これにより、ハードウェア情報の二重管理を解消できる。

#### 受け入れ基準

1. THE result.sh SHALL `case "$system"` によるハードウェア情報生成ブロック（cpu_name, gpu_name, cpu_cores, cpus_per_node, gpus_per_node の設定）を削除する
2. THE result.sh SHALL `uname_info` 変数の生成と使用を削除する
3. THE Result_JSON SHALL `cpu_name`、`gpu_name`、`cpu_cores`、`cpus_per_node`、`gpus_per_node`、`uname` フィールドを含まない
4. THE Result_JSON SHALL `code`、`system`、`FOM`、`FOM_version`、`Exp`、`node_count`、`numproc_node`、`description`、`confidential` フィールドを保持する
5. WHEN `fom_breakdown` が存在する場合、THE Result_JSON SHALL `fom_breakdown` フィールドも保持する

### 要件 13: Estimate_JSON への fom_breakdown 追加

**ユーザーストーリー:** 開発者として、Estimate_JSON の current_system と future_system にスケーリング後のFOM内訳を格納したい。これにより、推定結果の各区間の寄与を分析できる。

#### 受け入れ基準

1. THE Estimate_JSON の `current_system` オブジェクト SHALL `fom_breakdown` フィールドを持つ（ベンチマーク元に fom_breakdown が存在する場合）
2. THE Estimate_JSON の `future_system` オブジェクト SHALL `fom_breakdown` フィールドを持つ（ベンチマーク元に fom_breakdown が存在する場合）
3. THE Estimate_JSON の `fom_breakdown.sections` の各要素 SHALL スケーリング後の `time` 値を保持する
4. THE Estimate_JSON の `fom_breakdown.overlaps` の各要素 SHALL スケーリング後の `time` 値を保持する
5. THE estimate_common.sh の print_json 関数 SHALL `fom_breakdown` が設定されている場合に current_system と future_system 内に `fom_breakdown` を出力する
6. WHEN ベンチマーク元の Result_JSON に `fom_breakdown` が存在しない場合、THE Estimate_JSON SHALL current_system および future_system の `fom_breakdown` フィールドを省略する

### 要件 14: qws/run.sh の仮 SECTION/OVERLAP 出力

**ユーザーストーリー:** 開発者として、qws の run.sh に仮の SECTION/OVERLAP 行を追加し、FOM分解パイプラインの統合テストを行いたい。

#### 受け入れ基準

1. THE qws/run.sh SHALL FOM行の後に仮の SECTION行（`SECTION:区間名 time:秒` 形式）を `results/result` に出力する
2. THE qws/run.sh SHALL FOM行の後に仮の OVERLAP行（`OVERLAP:区間A,区間B time:秒` 形式）を `results/result` に出力する
3. THE qws/run.sh の仮 SECTION/OVERLAP 行 SHALL 統合テスト用の固定値を使用する
4. THE qws/run.sh SHALL `numproc_node` を `results/result` のFOM行に含める
