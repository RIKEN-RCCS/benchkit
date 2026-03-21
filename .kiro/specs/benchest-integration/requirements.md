# 要件定義書: 性能推定機能のBenchKit統合

## はじめに

BenchKitのCIパイプラインに性能推定（BenchEst）機能を統合する。ベンチマーク実行後に、推定スクリプトが用意されているアプリケーションに対してのみ自動で性能推定を行い、推定結果をresult_serverに送信する仕組みを構築する。性能推定モデルは現時点ではダミー実装とし、将来的に非公開リポジトリの実推定ツールに差し替え可能な設計とする。

### 性能推定の概要

性能推定は、ベンチマーク実行結果（演算区間・通信区間の時間データ）を基に、将来システムでの性能を推定する処理である。

- **推定対象システム**: 現状MiyabiGとRC_GH200のみに限定する。GH200が将来機に最もハードウェア的に近いため、これらのシステムでのみ有意な推定が可能。estimate.shが存在しても、対象外システムでは推定ジョブを生成しない
- **current_system（現行システム）**: Fugakuでの実測値を使用する。result_serverに蓄積された実測結果から、アプリごとに指定されたExpの最新結果を取得する
- **future_system（将来システム）**: 推定ツールにより算出する。演算区間はパフォーマンスカウンター生データを解析して将来機での性能を推定し、通信区間はスケーリングモデルで推定する
- **推定手法**: 複数の演算区間と通信区間の時間をそれぞれスケーリングした合計値から、通信と演算がオーバーラップしている時間を減じた時間が推定実行時間となる
- **演算区間の推定**: 現行機のパフォーマンスカウンター生データを解析して将来機での性能を推定するツール（非公開）で処理される。この処理がすべての演算区間に対して行われる

## 用語集

- **BenchKit**: ベンチマークの自動実行・結果収集を行うCI/CDフレームワーク
- **BenchEst**: 性能推定基盤。ベンチマーク結果に基づきターゲットシステムの性能を推定する
- **Estimate_Script**: `programs/<code>/estimate.sh` に配置されるアプリケーション別の推定スクリプト。存在するアプリかつ推定対象システム（MiyabiG, RC_GH200）でのみ推定が実行される
- **Estimate_Systems**: 推定対象システムのリスト。現状は `MiyabiG,RC_GH200` に固定。将来的に拡張可能
- **Estimate_Common**: `scripts/estimate_common.sh` に配置される推定処理の共通関数ライブラリ
- **Result_Server**: ベンチマーク結果および推定結果を受信・保存・表示するFlask Webサーバ
- **Send_Estimate_Script**: `scripts/send_estimate.sh` に配置される推定結果送信スクリプト
- **Matrix_Generator**: `scripts/matrix_generate.sh` に配置されるCI YAMLジェネレータ
- **Result_JSON**: ベンチマーク実行結果のJSONファイル（`results/result*.json`）
- **Estimate_JSON**: 推定結果のJSONファイル（`results/estimate*.json`）
- **FOM**: Figure of Merit。ベンチマークの性能指標値
- **PA_Data**: Performance Analysis Data。パフォーマンスカウンター生データを含むアーカイブ（`.tgz`）
- **CI_Pipeline**: GitLab CIの generate → trigger → build → run → send_results の実行パイプライン

## 要件

### 要件1: 推定共通関数ライブラリ

**ユーザーストーリー:** アプリケーション開発者として、推定スクリプトで共通的に使う関数群を利用したい。推定結果のJSON生成やベンチマーク結果の読み取りを毎回書かなくて済むようにしたい。

#### 受け入れ基準

1. THE Estimate_Common SHALL ベンチマーク Result_JSON からcode、exp、FOM、system、node_countの値を読み取る `read_values` 関数を提供する
2. THE Estimate_Common SHALL result_serverが期待するフォーマットに準拠した Estimate_JSON を生成する `print_json` 関数を提供する
3. THE Estimate_Common SHALL current_system（現行システム実測）とfuture_system（将来システム推定）の2つのターゲットシステムの結果を出力する
4. THE Estimate_Common SHALL benchmark_system、benchmark_fom、benchmark_nodes、code、exp、performance_ratioの各フィールドを Estimate_JSON に含める
5. WHEN `read_values` 関数に存在しないファイルパスが渡された場合、THEN THE Estimate_Common SHALL エラーメッセージを表示して非ゼロの終了コードを返す
6. WHEN `read_values` 関数にFOMフィールドを含まないJSONが渡された場合、THEN THE Estimate_Common SHALL エラーメッセージを表示して非ゼロの終了コードを返す


### 要件2: アプリケーション別推定スクリプト

**ユーザーストーリー:** アプリケーション開発者として、自分のアプリケーション固有の推定ロジックを自由に記述したい。推定モデルの中身はアプリごとに異なるため、フレームワーク化せず自由記述を許容する必要がある。

#### 受け入れ基準

1. THE Estimate_Script SHALL `programs/<code>/estimate.sh` のパスに配置される
2. WHEN Estimate_Script が実行される場合、THE Estimate_Script SHALL 第1引数として Result_JSON のファイルパスを受け取る
3. THE Estimate_Script SHALL Estimate_Common の `source` による読み込みと関数呼び出しにより推定結果を生成する
4. THE Estimate_Script SHALL 推定結果を `results/` ディレクトリ配下に `estimate*.json` として出力する
5. THE Estimate_Script SHALL アプリケーション開発者が推定ロジックを自由に記述できる構造を維持する（フレームワーク化しない）
6. WHEN 将来の実推定ツールに差し替える場合、THE Estimate_Script SHALL スクリプト内部の推定ロジック部分のみを変更することで対応可能とする
7. THE Estimate_Script SHALL `programs/<code>/estimate.sh` が存在しないアプリケーション、または推定対象システム以外では推定処理が実行されない（推定はオプショナル）

### 要件3: 推定結果送信スクリプト

**ユーザーストーリー:** CI/CDパイプラインの一部として、推定結果をresult_serverに自動送信したい。既存のsend_results.shと同様の仕組みで推定結果を送信する。

#### 受け入れ基準

1. THE Send_Estimate_Script SHALL `results/` ディレクトリ内の全ての `estimate*.json` ファイルを検出して送信する
2. THE Send_Estimate_Script SHALL Result_Server の `/api/ingest/estimate` エンドポイントにHTTP POSTで Estimate_JSON を送信する
3. THE Send_Estimate_Script SHALL 環境変数 `RESULT_SERVER` からサーバURLを取得する
4. THE Send_Estimate_Script SHALL 環境変数 `RESULT_SERVER_KEY` からAPIキーを取得し、`X-API-Key` ヘッダーに設定する
5. WHEN 送信対象の `estimate*.json` ファイルが存在しない場合、THE Send_Estimate_Script SHALL 警告メッセージを表示して正常終了する（エラーにしない）
6. IF HTTP POSTが失敗した場合、THEN THE Send_Estimate_Script SHALL エラーメッセージを表示して非ゼロの終了コードを返す

### 要件4: CIパイプラインへの推定ステージ統合

**ユーザーストーリー:** ベンチマーク実行後に、推定スクリプトが用意されているアプリケーションに対してのみ自動で性能推定が実行され、結果がresult_serverに送信されるようにしたい。

#### 受け入れ基準

1. THE Matrix_Generator SHALL 既存の `build → run → send_results` パイプラインに `estimate` ステージと `send_estimate` ステージを追加する
2. THE Matrix_Generator SHALL `estimate` ジョブを `send_results` ジョブの後に実行する（`needs` で依存関係を指定）
3. THE Matrix_Generator SHALL `send_estimate` ジョブを `estimate` ジョブの後に実行する
4. WHEN `programs/<code>/estimate.sh` が存在し、かつ対象システムが推定対象システム（MiyabiG, RC_GH200）である場合のみ、THE Matrix_Generator SHALL そのプログラム×システムの組み合わせに対して推定ジョブを生成する
5. WHEN `programs/<code>/estimate.sh` が存在しない場合、または対象システムが推定対象システムでない場合、THE Matrix_Generator SHALL そのプログラム×システムの組み合わせに対して推定ジョブおよび送信ジョブを一切生成しない（スキップする）
6. THE Matrix_Generator SHALL 推定ジョブのscriptセクションで `bash scripts/run_estimate.sh <code>` を呼び出す（複雑なロジックは別スクリプトに分離）
7. THE Matrix_Generator SHALL 推定ジョブが `results/` ディレクトリのartifactsを前段ジョブから引き継ぐ
8. THE Matrix_Generator SHALL YAML生成ルール（scriptセクションはシンプルに、複雑なロジックは別スクリプトに分離）に準拠する

### 要件5: 推定結果JSONフォーマット

**ユーザーストーリー:** result_serverの既存の推定結果表示機能と互換性のあるJSONフォーマットで推定結果を出力したい。既存のestimated_results.htmlテンプレートとresults_loader.pyが正しく動作する必要がある。

#### 受け入れ基準

1. THE Estimate_JSON SHALL 以下のトップレベルフィールドを含む: code, exp, benchmark_system, benchmark_fom, benchmark_nodes, current_system, future_system, performance_ratio
2. THE Estimate_JSON SHALL current_system オブジェクトに system, fom, nodes, method の各フィールドを含める
3. THE Estimate_JSON SHALL future_system オブジェクトに system, fom, nodes, method の各フィールドを含める
4. THE Estimate_JSON SHALL performance_ratio を current_system.fom と future_system.fom の比率として計算する
5. THE Estimate_JSON SHALL Result_Server の `load_estimated_results_table` 関数および `ESTIMATED_FIELD_MAP` と互換性のあるフォーマットとする

### 要件6: 推定ツール差し替え可能性

**ユーザーストーリー:** 将来、ダミーの推定モデルを非公開リポジトリの実推定ツールに差し替えたい。ハードウェア機密情報を含む実ツールはBenchKitの公開リポジトリには置かない。

#### 受け入れ基準

1. THE Estimate_Script SHALL 推定ロジック部分と共通処理部分（入力読み取り・出力生成）を分離した構造とする
2. THE Estimate_Common SHALL 推定モデルの実装に依存しない汎用的なインターフェースを提供する
3. WHEN 実推定ツールに差し替える場合、THE Estimate_Script SHALL estimate.sh内の推定ロジック部分のみの変更で対応可能とする
4. THE Estimate_Script SHALL 外部ツールの呼び出し（コマンド実行やスクリプト呼び出し）を推定ロジック部分に記述可能とする
5. THE 実推定ツール SHALL 複数の演算区間に対してパフォーマンスカウンター生データを解析し、将来機での性能を推定する処理を行う想定とする
6. THE Estimate_Script SHALL 演算区間と通信区間のスケーリング結果を合算し、オーバーラップ時間を減じる処理を記述可能な構造とする

### 要件7: ダミー推定モデルの提供

**ユーザーストーリー:** 統合テストやCI動作確認のために、実推定ツールがなくても動作するダミー推定モデルを提供したい。

#### 受け入れ基準

1. THE Estimate_Script SHALL デフォルトでダミー推定モデルを含む実装を提供する（qwsアプリ用）
2. THE Estimate_Script SHALL ダミーモデルとして、元のFOMに固定倍率を掛けた値をcurrent_systemおよびfuture_systemの推定FOMとする
3. THE Estimate_Script SHALL ダミーモデルの推定手法（method）を "scale-mock" と記録する

### 要件8: 推定トリガーモード（UUID指定による再推定）

**ユーザーストーリー:** 推定モデルを更新した際に、過去のベンチマーク結果に対して再推定を実行したい。UUID指定で特定の結果を再推定できるようにする。

#### 受け入れ基準

1. WHEN CI変数 `estimate_uuid` が指定された場合、THE CI_Pipeline SHALL 通常のbuild/runステージをスキップし、推定ステージのみを実行する
2. WHEN `estimate_uuid` が指定された場合、THE CI_Pipeline SHALL Result_Server から指定UUIDの Result_JSON を取得する
3. WHEN `estimate_uuid` が指定された場合、THE CI_Pipeline SHALL CI変数 `code` で指定されたプログラムの Estimate_Script を実行する
4. WHEN `estimate_uuid` が指定された場合、THE CI_Pipeline SHALL 推定結果を Result_Server に送信する
5. WHEN `estimate_uuid` と `code` の両方が指定されていない場合、THE CI_Pipeline SHALL エラーメッセージを表示する

### 要件9: 推定用ランナースクリプト

**ユーザーストーリー:** CIパイプラインの推定ジョブから呼び出される推定実行スクリプトを提供したい。YAML生成ルールに従い、複雑なロジックを別スクリプトに分離する。

#### 受け入れ基準

1. THE `scripts/run_estimate.sh` SHALL 第1引数としてプログラムコード名を受け取る
2. THE `scripts/run_estimate.sh` SHALL `results/` ディレクトリ内の Result_JSON を検出し、対応する `programs/<code>/estimate.sh` を実行する
3. THE `scripts/run_estimate.sh` SHALL 推定結果ファイル（estimate*.json）が `results/` ディレクトリに出力されることを確認する
4. WHEN Result_JSON が存在しない場合、THE `scripts/run_estimate.sh` SHALL 警告メッセージを表示して正常終了する
