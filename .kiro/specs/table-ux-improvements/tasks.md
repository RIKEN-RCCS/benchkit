# 実装計画: テーブルUX改善

## 概要

result_serverのサマリーテーブルに対する5つのUX改善を段階的に実装する。
バックエンド（`results_loader.py`）→ ルート（`results.py`）→ テンプレート（`_results_table.html`）→ CIスクリプト（`result.sh`）→ テスト更新の順で進め、各ステップで既存テストとの整合性を確認する。

## タスク

- [x] 1. `results_loader.py`: カラムリスト変更と`_build_row`更新
  - [x] 1.1 カラムリストからハードスペック系カラムを削除し、Proc/node・Thread/procを追加する
    - `load_results_table`内の`columns`リストを設計ドキュメントの順序に変更
    - ハードスペック系5カラム（CPU Name, GPU Name, CPU/node, GPU/node, CPU Core Count）を削除
    - `("Proc/node", "numproc_node")`を`("Nodes", "nodes")`の直後に追加
    - `("Thread/proc", "nthreads")`を`("Proc/node", "numproc_node")`の直後に追加
    - _Requirements: 3.1, 4.1, 5.1_

  - [x] 1.2 `_build_row`からハードスペック系フィールド抽出を削除し、numproc_node・nthreadsフィールドを追加する
    - `cpu`, `gpu`, `cpus`, `gpus`, `cpu_cores`の抽出コードとrowキーを削除
    - `numproc_node`フィールド抽出を追加（None/空文字列の場合は`"N/A"`にフォールバック）
    - `nthreads`フィールド抽出を追加（None/空文字列の場合は`"N/A"`にフォールバック）
    - _Requirements: 3.2, 4.2, 5.2_


  - [ ]* 1.3 Property 2: numproc_nodeフィールド抽出の正確性のプロパティテストを書く
    - **Property 2: numproc_nodeフィールド抽出の正確性**
    - ランダムなResult_JSONデータ（numproc_nodeあり/なし/None/空文字列）を生成し、`_build_row`の返すrowのnumproc_node値が期待値と一致することを検証
    - **Validates: Requirements 3.2, 3.5**

  - [ ]* 1.4 Property 3: nthreadsフィールド抽出の正確性のプロパティテストを書く
    - **Property 3: nthreadsフィールド抽出の正確性**
    - ランダムなResult_JSONデータ（nthreadsあり/なし/None/空文字列）を生成し、`_build_row`の返すrowのnthreads値が期待値と一致することを検証
    - **Validates: Requirements 4.2, 4.5**

  - [ ]* 1.5 Property 4: ハードスペック系カラムの非表示のプロパティテストを書く
    - **Property 4: ハードスペック系カラムの非表示**
    - ランダムなResult_JSONデータを生成し、`load_results_table`の返すカラムリストにハードスペック系カラムが含まれないことを検証
    - **Validates: Requirements 5.1**

- [x] 2. `results_loader.py`・`results.py`: カスケードフィルタ実装
  - [x] 2.1 `get_filter_options`に`filter_code`パラメータを追加し、Expフィルタリングロジックを実装する
    - `filter_code`キーワード引数を末尾に追加（デフォルト`None`）
    - `filter_code`指定時: そのCodeを持つJSONからのみExpを収集
    - `filter_code=None`または空文字列: 従来通り全Expを返す
    - _Requirements: 2.1, 2.2_

  - [x] 2.2 `results.py`の`_render_results_list`で`get_filter_options`呼び出しに`filter_code`を渡す
    - `filter_options = get_filter_options(received_dir, filter_code=filter_code, **filter_kwargs)`
    - _Requirements: 2.3_

  - [ ]* 2.3 Property 1: カスケードフィルタの正確性のプロパティテストを書く
    - **Property 1: カスケードフィルタの正確性**
    - ランダムなResult_JSONデータセット（複数のcode/exp組み合わせ）を生成し、`get_filter_options`の返すexpsが期待される集合と一致することを検証
    - **Validates: Requirements 2.1, 2.2**

- [x] 3. チェックポイント - バックエンド変更の確認
  - 全テストを実行し、パスすることを確認する。問題があればユーザーに質問する。

- [x] 4. `_results_table.html`: テンプレート更新
  - [x] 4.1 Compareカラムをテーブル左端からFOMカラムの右隣に移動する
    - ヘッダー: FOMカラムの`<th>`の直後にCompareの`<th>`を配置
    - ボディ: FOMセルの直後にチェックボックスセルを配置
    - ツールチップ: `tooltip-left`クラスを削除し、デフォルト方向を使用
    - 既存の比較機能（Select All Visible、Deselect All、Compare遷移）は変更しない
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 4.2 Proc/node・Thread/procカラムの描画を追加し、ハードスペック系カラムの描画を削除する
    - ヘッダーの`{% if col_name in [...] %}`リストに`"Proc/node"`, `"Thread/proc"`を追加
    - Proc/nodeツールチップ: "Number of processes per node"
    - Thread/procツールチップ: "Number of threads per process"
    - ボディの`{% elif key in [...] %}`リストに`"numproc_node"`, `"nthreads"`を追加
    - ハードスペック系カラム名をヘッダー・ボディの条件リストから削除
    - SYSTEMカラムのツールチップは変更しない
    - _Requirements: 3.3, 3.4, 3.5, 4.3, 4.4, 4.5, 5.3, 5.4_

- [x] 5. `result.sh`: nthreadsのFOM行パース追加
  - [x] 5.1 スクリプト冒頭に`nthreads`初期値を追加し、FOM行パースロジックに`nthreads:`パースを追加する
    - `nthreads=""`を`numproc_node=""`の近くに追加
    - `numproc_node`と同じパターンで`nthreads:`をパース: `grep -Eo 'nthreads:[ ]*[0-9]*'`
    - FOM行に`nthreads:`がない場合は空文字列を設定
    - FOMブロック開始時に`nthreads`をリセット
    - _Requirements: 4.6, 4.7_

  - [x] 5.2 `write_result_json`関数のJSON出力テンプレートに`nthreads`フィールドを追加する
    - `"numproc_node": "$numproc_node"`の直後に`"nthreads": "$nthreads"`を追加
    - LF改行を維持する（`.gitattributes`確認）
    - _Requirements: 4.6_

- [x] 6. テスト更新: 既存テストの期待値修正と新規テスト追加
  - [x] 6.1 `test_existing_columns_unchanged`の期待値を新カラムリストに更新する
    - ハードスペック系カラムを削除し、Proc/node・Thread/procを追加した期待値に変更
    - _Requirements: 3.1, 4.1, 5.1_

  - [x] 6.2 `test_existing_row_fields_preserved`の期待値を更新する
    - ハードスペック系フィールド（cpu_name, gpu_name等）のアサーションを削除
    - numproc_node・nthreadsフィールドのアサーションを追加
    - _Requirements: 3.2, 4.2, 5.2_

  - [x] 6.3 カスケードフィルタのユニットテストを追加する
    - `get_filter_options`に`filter_code`を渡した場合のExpフィルタリング動作確認
    - `filter_code=None`の場合に全Expが返ることの確認
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 6.4 numproc_node・nthreadsフォールバックのユニットテストを追加する
    - `numproc_node`なしのJSONで`"N/A"`が返ることを確認
    - `nthreads`なしのJSONで`"N/A"`が返ることを確認
    - _Requirements: 3.5, 4.5_

- [x] 7. 最終チェックポイント - 全テスト実行と動作確認
  - 全テストを実行し、99テスト＋新規テストが全てパスすることを確認する。問題があればユーザーに質問する。

## 備考

- `*`マーク付きタスクはオプショナルで、スキップ可能
- 各タスクは要件定義書の具体的な要件番号を参照
- チェックポイントで段階的に動作を検証
- プロパティテストはhypothesisを使用し、各プロパティの正確性を検証
- ユニットテストは具体的なエッジケースと統合動作を検証
- シェルスクリプトはLF改行を維持すること
