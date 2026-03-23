# Requirements Document

## Introduction

BenchKitのCIパイプラインにおいて、ベンチマークごとのbuild時間・queue時間・run時間を計測し、Result_JSONに記録する機能を追加する。さらに、実行モード（cross/native）およびCIトリガー種別（schedule/trigger/push/web/merge_request_event）もResult_JSONに含め、結果一覧ページの表に表示する。これにより、パイプラインの実行効率の把握とボトルネック特定を可能にする。

## Glossary

- **Pipeline_Timing_Collector**: CIパイプライン内でbuild時間・queue時間・run時間を計測し、結果ファイルに記録するシェルスクリプト群
- **Result_JSON**: ベンチマーク結果を格納するJSONファイル。result_serverに送信される
- **Result_Server**: FlaskベースのWebアプリケーション。Result_JSONの受信・保存・表示を行う
- **Results_Table**: result_serverの結果一覧ページ（results.html / results_confidential.html）に表示されるHTMLテーブル
- **Results_Loader**: Result_JSONファイルを読み込み、テーブル行データを構築するPythonモジュール（results_loader.py）
- **Matrix_Generator**: list.csvとsystem.csvからGitLab CI YAMLを自動生成するシェルスクリプト（matrix_generate.sh）
- **Execution_Mode**: ベンチマーク実行モード。crossモード（ビルドと実行を分離）またはnativeモード（ビルドと実行を同一ジョブで実行）
- **CI_Trigger_Source**: CIパイプラインのトリガー種別。GitLab CI変数 `$CI_PIPELINE_SOURCE` から取得される値（schedule, trigger, push, web, merge_request_event）
- **Build_Time**: buildジョブ（crossモード）またはbuild_runジョブ内のビルド処理にかかった秒数
- **Queue_Time**: ジョブがキューに投入されてから実際に実行開始されるまでの待機秒数
- **Run_Time**: runジョブ（crossモード）またはbuild_runジョブ内の実行処理にかかった秒数

## Requirements

### Requirement 1: パイプラインタイミング情報の計測

**User Story:** As a ベンチマーク管理者, I want CIパイプラインのbuild時間・queue時間・run時間を自動計測したい, so that パイプラインのボトルネックを特定できる

#### Acceptance Criteria

1. WHEN Matrix_Generator がcrossモードのジョブYAMLを生成する時, THE Matrix_Generator SHALL buildジョブのscriptセクションにビルド開始・終了時刻をファイルに記録するコマンドを含める
2. WHEN Matrix_Generator がcrossモードのジョブYAMLを生成する時, THE Matrix_Generator SHALL runジョブのscriptセクションに実行開始・終了時刻をファイルに記録するコマンドを含める
3. WHEN Matrix_Generator がnativeモードのジョブYAMLを生成する時, THE Matrix_Generator SHALL build_runジョブのscriptセクションにビルド開始・終了時刻および実行開始・終了時刻をファイルに記録するコマンドを含める
4. WHEN Matrix_Generator がrunジョブまたはbuild_runジョブのYAMLを生成する時, THE Matrix_Generator SHALL scriptセクションにqueue待機時間を計算するコマンドを含める
5. THE Pipeline_Timing_Collector SHALL 各時刻をUNIXエポック秒（整数）で記録する
6. THE Pipeline_Timing_Collector SHALL 計測した時刻データを `results/timing.env` ファイルに `KEY=VALUE` 形式で保存する

### Requirement 2: Result_JSONへのタイミング情報記録

**User Story:** As a ベンチマーク管理者, I want 計測したタイミング情報をResult_JSONに含めたい, so that 結果データと一緒にタイミング情報を保存・参照できる

#### Acceptance Criteria

1. WHEN result.sh がResult_JSONを生成する時, THE Pipeline_Timing_Collector SHALL `results/timing.env` からタイミング情報を読み込みResult_JSONに `pipeline_timing` オブジェクトとして追加する
2. THE Result_JSON の `pipeline_timing` オブジェクト SHALL `build_time`（秒数、数値型）フィールドを含む
3. THE Result_JSON の `pipeline_timing` オブジェクト SHALL `queue_time`（秒数、数値型）フィールドを含む
4. THE Result_JSON の `pipeline_timing` オブジェクト SHALL `run_time`（秒数、数値型）フィールドを含む
5. IF `results/timing.env` が存在しない場合, THEN THE Pipeline_Timing_Collector SHALL `pipeline_timing` フィールドを省略してResult_JSONを生成する

### Requirement 3: Result_JSONへの実行モード記録

**User Story:** As a ベンチマーク管理者, I want 実行モード（cross/native）をResult_JSONに記録したい, so that 結果がどのモードで実行されたか判別できる

#### Acceptance Criteria

1. WHEN Matrix_Generator がジョブYAMLを生成する時, THE Matrix_Generator SHALL 実行モード（cross または native）を環境変数またはスクリプト引数としてresult.shに渡す
2. WHEN result.sh がResult_JSONを生成する時, THE Pipeline_Timing_Collector SHALL `execution_mode` フィールドに実行モードの値を記録する
3. THE Result_JSON の `execution_mode` フィールド SHALL "cross" または "native" のいずれかの文字列値を持つ

### Requirement 4: Result_JSONへのCIトリガー種別記録

**User Story:** As a ベンチマーク管理者, I want CIパイプラインのトリガー種別をResult_JSONに記録したい, so that 定期実行・手動実行・push更新などの実行契機を把握できる

#### Acceptance Criteria

1. WHEN Matrix_Generator がジョブYAMLを生成する時, THE Matrix_Generator SHALL GitLab CI変数 `$CI_PIPELINE_SOURCE` をresult.shから参照可能にする
2. WHEN result.sh がResult_JSONを生成する時, THE Pipeline_Timing_Collector SHALL `ci_trigger` フィールドにCI_PIPELINE_SOURCEの値を記録する
3. THE Result_JSON の `ci_trigger` フィールド SHALL "schedule", "trigger", "push", "web", "merge_request_event" のいずれかの文字列値を持つ
4. IF CI_PIPELINE_SOURCE が取得できない場合, THEN THE Pipeline_Timing_Collector SHALL `ci_trigger` フィールドに "unknown" を記録する

### Requirement 5: 結果一覧テーブルへのタイミング情報表示

**User Story:** As a ベンチマーク利用者, I want 結果一覧ページでbuild時間・queue時間・run時間を確認したい, so that 各ベンチマークの実行効率を一覧で比較できる

#### Acceptance Criteria

1. THE Results_Loader SHALL Result_JSONから `pipeline_timing.build_time`, `pipeline_timing.queue_time`, `pipeline_timing.run_time` を読み取りテーブル行データに含める
2. THE Results_Table SHALL "Build Time", "Queue Time", "Run Time" の3つのカラムを表示する
3. WHEN `pipeline_timing` フィールドが存在しないResult_JSONを表示する時, THE Results_Table SHALL 該当セルに "-" を表示する
4. THE Results_Table SHALL タイミング値を人間が読みやすい形式（秒数）で表示する

### Requirement 6: 結果一覧テーブルへの実行モード表示

**User Story:** As a ベンチマーク利用者, I want 結果一覧ページで実行モードを確認したい, so that cross/nativeのどちらで実行されたか一目で分かる

#### Acceptance Criteria

1. THE Results_Loader SHALL Result_JSONから `execution_mode` を読み取りテーブル行データに含める
2. THE Results_Table SHALL "Mode" カラムを表示する
3. WHEN `execution_mode` フィールドが存在しないResult_JSONを表示する時, THE Results_Table SHALL 該当セルに "-" を表示する

### Requirement 7: 結果一覧テーブルへのCIトリガー種別表示

**User Story:** As a ベンチマーク利用者, I want 結果一覧ページでCIトリガー種別を確認したい, so that 各結果がどのような契機で実行されたか把握できる

#### Acceptance Criteria

1. THE Results_Loader SHALL Result_JSONから `ci_trigger` を読み取りテーブル行データに含める
2. THE Results_Table SHALL "Trigger" カラムを表示する
3. WHEN `ci_trigger` フィールドが存在しないResult_JSONを表示する時, THE Results_Table SHALL 該当セルに "-" を表示する

### Requirement 8: 既存Result_JSONとの後方互換性

**User Story:** As a ベンチマーク管理者, I want 新フィールドが存在しない既存のResult_JSONも正常に表示されるようにしたい, so that 過去の結果データが壊れない

#### Acceptance Criteria

1. WHEN Result_Server が `pipeline_timing` フィールドを持たないResult_JSONを読み込む時, THE Results_Loader SHALL エラーを発生させずにテーブル行を構築する
2. WHEN Result_Server が `execution_mode` フィールドを持たないResult_JSONを読み込む時, THE Results_Loader SHALL エラーを発生させずにテーブル行を構築する
3. WHEN Result_Server が `ci_trigger` フィールドを持たないResult_JSONを読み込む時, THE Results_Loader SHALL エラーを発生させずにテーブル行を構築する
4. THE Results_Table SHALL 新フィールドが存在しない行に対して "-" をフォールバック値として表示する
