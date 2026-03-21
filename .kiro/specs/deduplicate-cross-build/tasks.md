# 実装計画: crossモードbuildジョブ重複排除

## 概要

`scripts/matrix_generate.sh` を変更し、crossモードで同一 code+system ペアに対するbuildジョブを1回だけ生成する。bash連想配列（`declare -A`）で重複検出し、runジョブは共通のbuildジョブに依存させる。nativeモードのbuild_runジョブは新しい `build_run` ステージに配置し `needs: []` で即時開始可能にする。変更対象は `scripts/matrix_generate.sh` の1ファイルのみ。

## タスク

- [x] 1. stages定義の変更とBUILT_MAP連想配列の初期化
  - [x] 1.1 `scripts/matrix_generate.sh` の stages 定義を変更する
    - `build` と `run` の間に `build_run` ステージを追加
    - 変更後: `build, build_run, run, send_results, estimate, send_estimate`
    - _Requirements: 3.1_
  - [x] 1.2 メインループの前に `declare -A BUILT_MAP` を追加する
    - `for listfile in programs/*/list.csv` ループの直前に配置
    - _Requirements: 5.1, 5.3_

- [x] 2. crossモードのbuildジョブ重複排除とrunジョブの依存関係変更
  - [x] 2.1 crossモードのbuildジョブ生成を重複排除する
    - `build_key="${program}_${system}"` でキーを生成
    - `BUILT_MAP[$build_key]` が未設定の場合のみbuildジョブYAMLを出力
    - buildジョブ名を `${program}_${system}_build` に変更（実験パラメータを含めない）
    - buildジョブ出力後に `BUILT_MAP[$build_key]=1` で登録
    - 2回目以降の同一ペアではbuildジョブ出力をスキップ
    - buildジョブの内容（script, tags, artifacts）は変更しない
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 5.1, 5.2_
  - [x] 2.2 crossモードのrunジョブの `needs` フィールドを変更する
    - runジョブ名は従来通り `${job_prefix}_run` を維持
    - `needs` を `[${program}_${system}_build]` に変更
    - runジョブの内容（script, tags, variables等）は変更しない
    - _Requirements: 2.1, 2.2, 3.5_
  - [ ]* 2.3 Property 1: cross build の一意性と依存関係テスト
    - **Property 1: cross build の一意性と依存関係**
    - hypothesisでランダムなprogram名、system名、1〜5行のcross設定を生成し、一時list.csvを作成
    - subprocess経由で `matrix_generate.sh` を実行し、生成YAMLをパース
    - 当該 code+system ペアのbuildジョブがちょうど1つ存在し、全runジョブのneedsが正しいことを検証
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.2, 3.5, 5.2**
  - [ ]* 2.4 Property 2: ジョブ名形式と後続ジョブチェーンの正確性テスト
    - **Property 2: ジョブ名形式と後続ジョブチェーンの正確性**
    - hypothesisでランダムなcross設定を生成し、生成YAMLをパース
    - runジョブ名が `{program}_{system}_N{nodes}_P{numproc_node}_T{nthreads}_run` 形式であること、send_resultsジョブ名が対応する形式であること、send_resultsのneedsが対応するrunジョブを参照していることを検証
    - **Validates: Requirements 2.1, 2.3, 4.1, 4.3**

- [x] 3. nativeモードのステージ変更と即時開始設定
  - [x] 3.1 nativeモードの build_run ジョブのステージと needs を変更する
    - `stage: build` → `stage: build_run` に変更
    - `needs: []` を追加（buildステージの完了を待たずに即時開始）
    - ジョブ名・内容は変更しない
    - _Requirements: 3.2, 3.3, 3.4_
  - [ ]* 3.2 Property 3: native モードのステージ配置と即時開始テスト
    - **Property 3: native モードのステージ配置と即時開始**
    - hypothesisでランダムなnative設定を生成し、生成YAMLをパース
    - build_runジョブの `stage` が `build_run` であること、`needs` が空配列であること、ジョブ名が従来通りの形式であることを検証
    - **Validates: Requirements 3.2, 3.3, 3.4**

- [x] 4. チェックポイント - 変更の動作確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問してください。

- [x] 5. 後続ジョブチェーンの正確性確認と最終統合
  - [x] 5.1 後続ジョブ（send_results, estimate, send_estimate）の依存関係が正しいことを確認する
    - crossモード: `emit_send_results_job` の第2引数が `${job_prefix}_run` であることを確認（変更不要）
    - nativeモード: `emit_send_results_job` の第2引数が `${job_prefix}_build_run` であることを確認（変更不要）
    - estimate/send_estimate の依存関係も従来通り正しいことを確認（変更不要）
    - _Requirements: 4.1, 4.2, 4.3_
  - [ ]* 5.2 単体テスト: 具体的な入力パターンの検証
    - 同一system cross 2行（scale-letkf Fugaku N3/N75）: build 1つ、run 2つ、両runが同一buildに依存
    - cross + native 混在: build 1つ(cross)、build_run 1つ(native)
    - stages定義: `build, build_run, run, send_results, estimate, send_estimate` の順
    - native の needs: `needs: []` が存在
    - native の stage: `stage: build_run`
    - _Requirements: 1.1, 1.2, 2.2, 3.1, 3.2, 3.3_

- [x] 6. 最終チェックポイント - 全テスト通過確認
  - すべてのテストが通ることを確認し、不明点があればユーザーに質問してください。

## 備考

- `*` マーク付きタスクはオプショナルで、MVP実装時にはスキップ可能
- 各タスクは対応する要件番号を参照しており、トレーサビリティを確保
- プロパティテストは対応する実装タスクの直後に配置し、早期にバグを検出
- テストはPython hypothesis + subprocess で `matrix_generate.sh` を実行し、生成YAMLをPyYAMLでパースして検証
- テストはbashスクリプトのためWindows環境では実行不可
- YAML生成ルール（yaml-generation.md）を遵守: scriptセクションはシンプルに、禁止構文を使用しない
