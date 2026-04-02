# 実装計画: パイプライン結果ステージリファクタリング

## 概要

`result.sh` と `collect_timing.sh` の実行場所を計算ノード（run/build_run ジョブ）から Docker ランナー（send_results ジョブ）に移動する。主な変更対象は `scripts/job_functions.sh`（`emit_send_results_job` 拡張）と `scripts/matrix_generate.sh`（run/build_run ジョブからのスクリプト除去）。テストは Python（Hypothesis）で生成 YAML を検証する。

## タスク

- [x] 1. `emit_send_results_job` 関数の拡張（`scripts/job_functions.sh`）
  - [x] 1.1 `emit_send_results_job` 関数のシグネチャを拡張し、新しい引数（program, system, mode, build_job, run_job）を追加する
    - 現在の3引数（job_prefix, depends_on, output）に加え、$4=program, $5=system, $6=mode, $7=build_job, $8=run_job を追加
    - _要件: 5.1_
  - [x] 1.2 `emit_send_results_job` が生成する YAML の script セクションを変更し、`collect_timing.sh` → `result.sh` → `send_results.sh` の順で出力する
    - `bash scripts/collect_timing.sh` を最初に出力
    - `bash scripts/result.sh {program} {system} {mode} {build_job} {run_job} $CI_PIPELINE_ID` を出力
    - `bash scripts/send_results.sh` を最後に出力
    - _要件: 5.2, 5.3, 5.4, 5.5, 3.1, 3.2, 3.3, 3.5_
  - [x] 1.3 `emit_send_results_job` が生成する YAML に artifacts ブロックを追加する
    - `results/` パスを artifacts に含め、`expire_in: 1 week` を設定
    - estimate ジョブが send_results ジョブのアーティファクトから `result*.json` を取得できるようにする
    - _要件: 7.4_

- [x] 2. `matrix_generate.sh` の Cross_Mode run ジョブ変更
  - [x] 2.1 Cross_Mode の run ジョブ script セクションから `collect_timing.sh` と `result.sh` の呼び出し行、および関連するデバッグ出力行を除去する
    - 除去対象: `bash scripts/collect_timing.sh`, `bash scripts/result.sh ...`, `echo "After result.sh execution"`, `ls -la results/`, `echo "Results directory contents count"`, `ls results/ | wc -l`
    - _要件: 1.1, 1.2_
  - [x] 2.2 Cross_Mode の `emit_send_results_job` 呼び出しを新しいシグネチャに更新する
    - `emit_send_results_job "$job_prefix" "${job_prefix}_run" "$OUTPUT_FILE" "$program" "$system" "cross" "${build_key}_build" "${job_prefix}_run"` に変更
    - _要件: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 3. `matrix_generate.sh` の Native_Mode build_run ジョブ変更
  - [x] 3.1 Native_Mode の build_run ジョブ script セクションから `collect_timing.sh` と `result.sh` の呼び出し行、および関連するデバッグ出力行を除去する
    - 除去対象: `bash scripts/collect_timing.sh`, `bash scripts/result.sh ...`, `echo "After result.sh execution"`, `ls -la results/`, `echo "Results directory contents count"`, `ls results/ | wc -l`
    - _要件: 2.1, 2.2_
  - [x] 3.2 Native_Mode の `emit_send_results_job` 呼び出しを新しいシグネチャに更新する
    - `emit_send_results_job "$job_prefix" "${job_prefix}_build_run" "$OUTPUT_FILE" "$program" "$system" "native" "${job_prefix}_build_run" "${job_prefix}_build_run"` に変更
    - _要件: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 4. チェックポイント - コア実装の確認
  - すべてのコード変更が正しいことを確認し、ユーザーに質問があれば確認する。

- [ ] 5. プロパティベーステストの作成
  - [ ]* 5.1 Property 1 のテスト: 計算ジョブから結果処理スクリプトが除去されていること
    - **Property 1: 計算ジョブから結果処理スクリプトが除去されていること**
    - テスト用 list.csv / system.csv を Hypothesis で動的生成し、`matrix_generate.sh` を実行して YAML を検証
    - run/build_run ジョブの script セクションに `collect_timing.sh` / `result.sh` が含まれないことを確認
    - **検証対象: 要件 1.1, 1.2, 2.1, 2.2**
  - [ ]* 5.2 Property 2 のテスト: send_results ジョブのスクリプト実行順序
    - **Property 2: send_results ジョブのスクリプト実行順序**
    - send_results ジョブの script セクションで `collect_timing.sh` → `result.sh` → `send_results.sh` の順序を検証
    - **検証対象: 要件 3.1, 3.2, 3.5, 5.2, 5.3, 5.4**
  - [ ]* 5.3 Property 3 のテスト: result.sh の引数の正当性
    - **Property 3: result.sh の引数の正当性**
    - send_results ジョブの `result.sh` 呼び出し行を正規表現でパースし、引数が `bash scripts/result.sh P S M B R $CI_PIPELINE_ID` の形式であることを検証
    - **検証対象: 要件 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.3**
  - [ ]* 5.4 Property 4 のテスト: send_results ジョブの依存関係とタグ
    - **Property 4: send_results ジョブの依存関係とタグ**
    - send_results ジョブの `tags` に `fncx-curl-jq` が含まれ、`needs` に正しい前段ジョブが指定されていることを検証
    - **検証対象: 要件 3.4, 6.1, 6.2**
  - [ ]* 5.5 Property 5 のテスト: YAML 生成ルール準拠
    - **Property 5: YAML 生成ルール準拠**
    - send_results ジョブの script セクション各行にリダイレクト、パイプ、論理演算子、条件文が含まれないことを検証
    - **検証対象: 要件 5.5**
  - [ ]* 5.6 Property 6 のテスト: estimate ジョブの依存関係維持
    - **Property 6: estimate ジョブの依存関係維持**
    - estimate 対象システムかつ estimate スクリプトを持つプログラムにおいて、estimate ジョブの `needs` に send_results ジョブが含まれていることを検証
    - **検証対象: 要件 7.4**

- [x] 6. チェックポイント - テスト確認
  - すべてのテストが通ることを確認し、ユーザーに質問があれば確認する。

- [x] 7. ドキュメント更新
  - [x] 7.1 `README.md` の「CI パイプラインの構成」セクションを更新する
    - 「ベンチマーク実行パイプライン」セクションで、`collect_timing.sh` と `result.sh` が send_results ステージで実行されることを反映
    - `record_timestamp.sh` は引き続き run/build_run ジョブ内で使用されることを明記
    - _要件: 8.1, 8.2_
  - [x] 7.2 `ADD_APP.md` にパイプラインフロー変更の影響がある記述があれば更新する
    - run.sh の実行環境に関する記述を確認し、必要に応じて更新
    - _要件: 8.3_

- [x] 8. 最終チェックポイント - 全体確認
  - すべてのテストが通ること、ドキュメントが更新されていることを確認し、ユーザーに質問があれば確認する。

## 備考

- `*` マーク付きタスクはオプションであり、MVP では省略可能
- 各タスクは特定の要件を参照しており、トレーサビリティを確保
- チェックポイントで段階的な検証を実施
- プロパティテストは生成された YAML 出力を Python（Hypothesis）で検証する形式
- `result.sh`, `collect_timing.sh`, `send_results.sh` 自体のロジックは変更しない
