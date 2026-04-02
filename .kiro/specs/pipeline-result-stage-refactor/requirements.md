# 要件定義書: パイプライン結果ステージリファクタリング

## はじめに

本機能は、CIパイプラインにおける `result.sh`（結果JSON生成）と `collect_timing.sh`（タイミング集計）の実行を、高コストな計算ノード上の run/build_run ジョブから、軽量な Docker ランナー上の send_results ステージに移動するリファクタリングである。これにより計算ノードの占有時間を削減し、パイプラインのコスト効率を向上させる。

## 用語集

- **Matrix_Generator**: `scripts/matrix_generate.sh` — list.csv と system.csv を読み込み、GitLab CI YAML（`.gitlab-ci.generated.yml`）を自動生成するスクリプト
- **Result_Processor**: `scripts/result.sh` — `results/result` ファイルを解析し、JSON ファイル（`results/result[0-9].json`）を生成するスクリプト
- **Timing_Collector**: `scripts/collect_timing.sh` — タイムスタンプファイルから build/run 時間を算出し `results/timing.env` を生成するスクリプト
- **Result_Sender**: `scripts/send_results.sh` — 結果 JSON を結果サーバに転送するスクリプト
- **Compute_Runner**: 計算ノード上で動作する GitLab Runner（Jacamar-CI 経由でバッチジョブを実行）
- **Docker_Runner**: `fncx-curl-jq` タグを持つ軽量 Docker ランナー（bash, curl, jq, git, md5sum が利用可能）
- **Cross_Mode**: ビルドとランを別ジョブで実行するモード（build → run の2段階）
- **Native_Mode**: ビルドとランを同一ジョブ（build_run）で実行するモード
- **Timestamp_File**: `results/build_start`, `results/build_end`, `results/run_start`, `results/run_end` — Unix エポック秒を記録したファイル
- **Result_File**: `results/result` — run.sh が出力する FOM/SECTION/OVERLAP 行を含むテキストファイル
- **Source_Info_File**: `results/source_info.env` — ビルド時に記録されるソースコード情報ファイル

## 要件

### 要件 1: run ジョブからの result.sh / collect_timing.sh 除去（Cross_Mode）

**ユーザーストーリー:** CIパイプライン管理者として、Cross_Mode の run ジョブから結果処理スクリプトを除去したい。計算ノードの占有時間を削減するためである。

#### 受け入れ基準

1. WHEN Matrix_Generator が Cross_Mode のジョブを生成するとき、THE Matrix_Generator は run ジョブの script セクションに `collect_timing.sh` の呼び出しを含めないこと
2. WHEN Matrix_Generator が Cross_Mode のジョブを生成するとき、THE Matrix_Generator は run ジョブの script セクションに `result.sh` の呼び出しを含めないこと
3. WHEN Cross_Mode の run ジョブが完了したとき、THE run ジョブは artifacts として `results/result`, `results/source_info.env`, `results/build_start`, `results/build_end`, `results/run_start`, `results/run_end` を含むこと
4. WHEN Cross_Mode の run ジョブが完了したとき、THE run ジョブは artifacts として `results/padata*.tgz` が存在する場合それも含むこと

### 要件 2: build_run ジョブからの result.sh / collect_timing.sh 除去（Native_Mode）

**ユーザーストーリー:** CIパイプライン管理者として、Native_Mode の build_run ジョブから結果処理スクリプトを除去したい。計算ノードの占有時間を削減するためである。

#### 受け入れ基準

1. WHEN Matrix_Generator が Native_Mode のジョブを生成するとき、THE Matrix_Generator は build_run ジョブの script セクションに `collect_timing.sh` の呼び出しを含めないこと
2. WHEN Matrix_Generator が Native_Mode のジョブを生成するとき、THE Matrix_Generator は build_run ジョブの script セクションに `result.sh` の呼び出しを含めないこと
3. WHEN Native_Mode の build_run ジョブが完了したとき、THE build_run ジョブは artifacts として `results/result`, `results/source_info.env`, `results/build_start`, `results/build_end`, `results/run_start`, `results/run_end` を含むこと
4. WHEN Native_Mode の build_run ジョブが完了したとき、THE build_run ジョブは artifacts として `results/padata*.tgz` が存在する場合それも含むこと

### 要件 3: send_results ジョブへの collect_timing.sh / result.sh 追加

**ユーザーストーリー:** CIパイプライン管理者として、send_results ジョブで collect_timing.sh と result.sh を実行したい。軽量な Docker_Runner 上で結果処理を行うためである。

#### 受け入れ基準

1. WHEN Matrix_Generator が send_results ジョブを生成するとき、THE Matrix_Generator は script セクションで `collect_timing.sh` を `result.sh` より前に実行すること
2. WHEN Matrix_Generator が send_results ジョブを生成するとき、THE Matrix_Generator は script セクションで `result.sh` を `send_results.sh` より前に実行すること
3. THE Matrix_Generator は send_results ジョブの `result.sh` 呼び出しに正しい引数（program, system, mode, build_job, run_job, pipeline_id）を渡すこと
4. WHEN send_results ジョブが Docker_Runner 上で実行されるとき、THE send_results ジョブは `fncx-curl-jq` タグを使用すること
5. THE send_results ジョブの実行順序は `collect_timing.sh` → `result.sh` → `send_results.sh` であること

### 要件 4: result.sh 引数の Matrix_Generator からの受け渡し

**ユーザーストーリー:** CIパイプライン管理者として、result.sh に必要な引数を send_results ジョブに正しく渡したい。matrix_generate.sh の生成時点で全引数が確定しているためである。

#### 受け入れ基準

1. THE Matrix_Generator は send_results ジョブの `result.sh` 呼び出しに program 名を第1引数として渡すこと
2. THE Matrix_Generator は send_results ジョブの `result.sh` 呼び出しに system 名を第2引数として渡すこと
3. THE Matrix_Generator は send_results ジョブの `result.sh` 呼び出しに mode（cross または native）を第3引数として渡すこと
4. THE Matrix_Generator は send_results ジョブの `result.sh` 呼び出しに build_job 名を第4引数として渡すこと
5. THE Matrix_Generator は send_results ジョブの `result.sh` 呼び出しに run_job 名を第5引数として渡すこと
6. THE Matrix_Generator は send_results ジョブの `result.sh` 呼び出しに `$CI_PIPELINE_ID` を第6引数として渡すこと

### 要件 5: emit_send_results_job 関数の拡張

**ユーザーストーリー:** 開発者として、emit_send_results_job 関数を拡張し、collect_timing.sh と result.sh の実行を含めたい。send_results ジョブの生成ロジックを一元管理するためである。

#### 受け入れ基準

1. THE emit_send_results_job 関数は、result.sh に必要な引数（program, system, mode, build_job, run_job）を受け取ること
2. WHEN emit_send_results_job が呼び出されたとき、THE 関数は script セクションに `bash scripts/collect_timing.sh` を出力すること
3. WHEN emit_send_results_job が呼び出されたとき、THE 関数は script セクションに `bash scripts/result.sh` と全引数を出力すること
4. WHEN emit_send_results_job が呼び出されたとき、THE 関数は script セクションに `bash scripts/send_results.sh` を出力すること
5. THE emit_send_results_job 関数が生成する YAML は、GitLab CI YAML 生成ルール（シンプルなコマンド、リダイレクト禁止、パイプ禁止）に準拠すること

### 要件 6: アーティファクト依存関係の維持

**ユーザーストーリー:** CIパイプライン管理者として、send_results ジョブが前段ジョブのアーティファクトを正しく取得できるようにしたい。結果処理に必要なファイルが揃っている必要があるためである。

#### 受け入れ基準

1. WHEN Cross_Mode の send_results ジョブが実行されるとき、THE send_results ジョブは `needs` で run ジョブを指定し、そのアーティファクトを取得すること
2. WHEN Native_Mode の send_results ジョブが実行されるとき、THE send_results ジョブは `needs` で build_run ジョブを指定し、そのアーティファクトを取得すること
3. WHEN send_results ジョブが開始されたとき、THE send_results ジョブは `results/result` ファイルにアクセスできること
4. WHEN send_results ジョブが開始されたとき、THE send_results ジョブは Timestamp_File（build_start, build_end, run_start, run_end）にアクセスできること

### 要件 7: 後方互換性の維持

**ユーザーストーリー:** CIパイプライン管理者として、リファクタリング後もパイプラインの最終出力が変わらないことを保証したい。既存の結果サーバとの互換性を維持するためである。

#### 受け入れ基準

1. THE send_results ジョブが生成する `results/result[0-9].json` のスキーマは、リファクタリング前と同一であること
2. THE send_results ジョブが生成する `results/timing.env` のフォーマットは、リファクタリング前と同一であること
3. THE Result_Sender が結果サーバに送信するデータは、リファクタリング前と同一の形式であること
4. WHEN estimate ジョブが存在する場合、THE estimate ジョブは send_results ジョブの完了後に正しく実行されること

### 要件 8: ドキュメントの更新

**ユーザーストーリー:** 開発者として、README.md と ADD_APP.md がリファクタリング後のパイプライン構造を正しく反映していることを確認したい。新規参加者が正確な情報を得られるようにするためである。

#### 受け入れ基準

1. WHEN リファクタリングが完了したとき、THE README.md の「CI パイプラインの構成」セクションは新しいパイプラインフロー（run ジョブでは result.sh/collect_timing.sh を実行せず、send_results ジョブで実行する）を反映すること
2. WHEN リファクタリングが完了したとき、THE README.md の「ベンチマーク実行パイプライン」セクションは send_results ステージの役割変更を反映すること
3. WHEN リファクタリングが完了したとき、THE ADD_APP.md はパイプラインフローの変更に影響する記述がある場合、それを更新すること
