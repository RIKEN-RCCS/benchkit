# 要件ドキュメント: パイプラインスクリプトのリファクタリング

## はじめに

BenchKit の CI/CD パイプライン生成・結果処理に関わるシェルスクリプト群の保守性向上を目的としたリファクタリング。scripts/ 配下の主要スクリプトおよび benchpark-bridge/scripts/ の各スクリプトを対象とする。既存の動作を一切変更せず、重複コードの共通化、不要コードの除去、構造の整理を行う。

**対象外:**
- `programs/*/build.sh`, `programs/*/run.sh` — アプリ開発者が最低限のルールのもと自由に記述する領域であり、フレームワーク的な抽象化・共通関数化は行わない。参加の敷居を下げる戦略として意図的にシンプルに保つ。
- `result_server/` — 前回のクリーンアップで完了済み。

## 用語集

- **Pipeline_Generator**: GitLab CI の YAML 設定ファイルを動的に生成するスクリプト群（scripts/matrix_generate.sh, benchpark-bridge/scripts/ci_generator.sh）
- **Result_Processor**: ベンチマーク実行結果を JSON 形式に変換するスクリプト（scripts/result.sh）
- **Result_Sender**: 変換済み JSON を結果サーバに送信するスクリプト（scripts/send_results.sh）
- **NFS_Waiter**: NFS ファイル同期を待機するスクリプト（scripts/wait_for_nfs.sh）
- **Job_Functions**: パイプライン生成で使用される共通関数ライブラリ（scripts/job_functions.sh）
- **BenchPark_Common**: BenchPark 統合用の共通関数ライブラリ（benchpark-bridge/scripts/common.sh）
- **BenchPark_CI_Generator**: BenchPark 用の GitLab CI YAML 生成スクリプト（benchpark-bridge/scripts/ci_generator.sh）
- **BenchPark_Runner**: BenchPark 実験の実行管理スクリプト（benchpark-bridge/scripts/runner.sh）
- **BenchPark_Converter**: BenchPark 結果を BenchKit 形式に変換する Python スクリプト（benchpark-bridge/scripts/result_converter.py）
- **List_CSV**: 各プログラムの実行構成を定義する CSV ファイル（programs/*/list.csv）
- **Test_Submitter**: ローカルテスト用のジョブ投入スクリプト（scripts/test_submit.sh）

## 要件

### 要件 1: CSV 読み込みロジックの共通化

**ユーザーストーリー:** 開発者として、list.csv の読み込み・パース処理を共通関数に集約したい。matrix_generate.sh と ci_generator.sh で同一パターンの CSV パースが重複しているため。

#### 受け入れ基準

1. THE Job_Functions SHALL list.csv のヘッダースキップ、コメント行スキップ、空白トリムを行う共通 CSV 読み込み関数を提供する
2. WHEN list.csv の読み込みが必要な場合、THE Pipeline_Generator SHALL 共通 CSV 読み込み関数を使用する
3. THE Job_Functions SHALL 共通 CSV 読み込み関数で、フィールド（system, mode, queue_group, nodes, numproc_node, nthreads, elapse）を変数にエクスポートする
4. THE Job_Functions SHALL 統合前と同一のパース結果を返す（ヘッダー行とコメント行のスキップ、各フィールドの空白トリム）

### 要件 2: フィルタリングロジックの共通化

**ユーザーストーリー:** 開発者として、system フィルタと code フィルタのマッチング処理を共通関数に集約したい。matrix_generate.sh と ci_generator.sh で同一パターンのカンマ区切りフィルタ処理が重複しているため。

#### 受け入れ基準

1. THE Job_Functions SHALL カンマ区切りフィルタ文字列と対象値を受け取り、マッチ判定を返す共通フィルタ関数を提供する
2. WHEN system フィルタまたは code フィルタの適用が必要な場合、THE Pipeline_Generator SHALL 共通フィルタ関数を使用する
3. THE Job_Functions SHALL フィルタ文字列が空の場合、常にマッチと判定する
4. THE Job_Functions SHALL 統合前と同一のフィルタリング結果を返す

### 要件 3: 不要スクリプトの特定と除去

**ユーザーストーリー:** 開発者として、使用されていないスクリプトを除去したい。scripts/ 配下に CI パイプラインや他スクリプトから参照されていないファイルが存在し、保守対象を不必要に増やしているため。

#### 受け入れ基準

1. THE Pipeline_Generator SHALL scripts/ 配下の各スクリプトについて、.gitlab-ci.yml、matrix_generate.sh、他のスクリプトのいずれからも呼び出されていないファイルを除去対象として特定する
2. THE Pipeline_Generator SHALL 除去対象ファイルの削除後も、CI パイプラインの全ジョブが正常に動作する

### 要件 4: matrix_generate.sh と ci_generator.sh の YAML 生成パターン共通化

**ユーザーストーリー:** 開発者として、2つの YAML 生成スクリプト間で重複する YAML ブロック出力パターンを共通化したい。send_results ジョブの定義、artifacts 設定、id_tokens 設定が両スクリプトで重複しているため。

#### 受け入れ基準

1. THE Job_Functions SHALL send_results ジョブの YAML ブロックを生成する共通関数を提供する（ジョブ名プレフィックスと依存ジョブ名をパラメータとして受け取る）
2. THE Job_Functions SHALL artifacts 設定の YAML ブロックを生成する共通関数を提供する（パスと有効期限をパラメータとして受け取る）
3. WHEN YAML ジョブ定義の生成が必要な場合、THE Pipeline_Generator SHALL 共通関数を使用する
4. THE Pipeline_Generator SHALL 統合前と同一の YAML 出力を生成する

### 要件 5: test_submit.sh のシステム別投入ロジック整理

**ユーザーストーリー:** 開発者として、test_submit.sh のシステム別ジョブ投入処理を case 文に統合したい。if 文の連鎖で記述されており、新システム追加時に見落としやすい構造になっているため。

#### 受け入れ基準

1. THE Test_Submitter SHALL システム別のジョブ投入処理を単一の case 文で記述する
2. THE Test_Submitter SHALL 未知のシステムに対してエラーメッセージを出力して終了する
3. THE Test_Submitter SHALL 統合前と同一のジョブ投入コマンドを生成する（pjsub, sbatch, qsub の各パラメータが一致する）

### 要件 6: BenchPark CI ジョブ定義の重複排除

**ユーザーストーリー:** 開発者として、ci_generator.sh 内の SEND_ONLY モードと通常モードで重複する convert ジョブと send ジョブの定義を共通化したい。同一の YAML ブロックが2箇所に記述されており、修正時に片方を忘れるリスクがあるため。

#### 受け入れ基準

1. THE BenchPark_CI_Generator SHALL convert ジョブの YAML 定義を生成する共通関数を持つ
2. THE BenchPark_CI_Generator SHALL send ジョブの YAML 定義を生成する共通関数を持つ
3. WHEN SEND_ONLY モードの場合、THE BenchPark_CI_Generator SHALL convert と send のみを生成する
4. WHEN 通常モードの場合、THE BenchPark_CI_Generator SHALL setup、run、convert、send を生成する
5. THE BenchPark_CI_Generator SHALL 統合前と同一の YAML 出力を生成する

### 要件 7: BenchPark common.sh の未使用関数の整理

**ユーザーストーリー:** 開発者として、benchpark-bridge/scripts/common.sh 内の未使用関数を特定し整理したい。将来の拡張用に定義されたが現在どこからも呼び出されていない関数が存在し、コードの見通しを悪くしているため。

#### 受け入れ基準

1. THE BenchPark_Common SHALL runner.sh および ci_generator.sh から呼び出されていない関数を特定する
2. THE BenchPark_Common SHALL 未使用関数に対して、将来使用予定であることを示すコメントを付与するか、除去する
3. IF 未使用関数を除去する場合、THEN THE BenchPark_Common SHALL 除去後も runner.sh および ci_generator.sh が正常に動作する
