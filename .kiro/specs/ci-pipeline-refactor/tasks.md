# 実装計画: CI基盤リファクタリングと堅牢化

## 概要

本計画は、CIパイプライン基盤のリファクタリングを段階的に実装する。依存関係に基づき、独立したコンポーネント（bk_functions.sh）から着手し、CSV形式の変更、スクリプト更新、マイグレーション、テストの順に進める。実装言語はBash（シェルスクリプト）、テストはPython（Hypothesis）を使用する。

## タスク

- [x] 1. bk_functions.sh の新規作成
  - [x] 1.1 `scripts/bk_functions.sh` を新規作成し、bk_emit_result 関数を実装する
    - `--fom`（必須、数値）、`--fom-version`、`--exp`、`--nodes`、`--numproc-node`、`--nthreads`、`--confidential` の名前付き引数をパース
    - `--fom` 未指定時・非数値時は stderr にエラー出力し exit code 1
    - 省略された引数の key:value ペアは出力しない
    - POSIX互換（jq不要）
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_
  - [x] 1.2 bk_emit_section 関数を実装する
    - 位置引数2つ（セクション名、時間値）
    - 引数不足時・time非数値時は stderr にエラー出力し exit code 1
    - 出力形式: `SECTION:<name> time:<time>`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - [x] 1.3 bk_emit_overlap 関数を実装する
    - 位置引数2つ（カンマ区切りセクション名、時間値）
    - 引数不足時・time非数値時は stderr にエラー出力し exit code 1
    - 出力形式: `OVERLAP:<section_names> time:<time>`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 1.4 bk_emit_result のプロパティベーステストを作成する
    - `scripts/tests/test_bk_functions.py` を新規作成
    - **Property 5: bk_emit_resultの出力正当性**
    - **Validates: Requirements 4.2, 4.6, 4.7**
  - [ ]* 1.5 bk_functions 数値バリデーションのプロパティベーステストを作成する
    - **Property 6: bk_functions数値バリデーション**
    - **Validates: Requirements 4.5, 5.5, 6.5**
  - [ ]* 1.6 bk_emit_section のプロパティベーステストを作成する
    - **Property 8: bk_emit_sectionの出力フォーマット**
    - **Validates: Requirements 5.2, 5.6**
  - [ ]* 1.7 bk_emit_overlap のプロパティベーステストを作成する
    - **Property 9: bk_emit_overlapの出力フォーマット**
    - **Validates: Requirements 6.2, 6.6**
  - [ ]* 1.8 bk_emit出力とResult_Parserの往復互換性テストを作成する
    - **Property 7: bk_emit出力とResult_Parserの往復互換性**
    - **Validates: Requirements 4.9, 5.7, 6.7**

- [x] 2. チェックポイント - bk_functions.sh の動作確認
  - 全テストが通ることを確認し、不明点があればユーザーに質問する

- [x] 3. config/system.csv の再設計
  - [x] 3.1 `config/system.csv` を1システム1行の新形式に書き換える
    - ヘッダ: `system,mode,tag_build,tag_run,queue,queue_group`
    - 旧形式の複数行（build/run/build_run）を1行に統合
    - mode=cross: tag_build と tag_run を両方設定
    - mode=native: tag_build は空、tag_run のみ設定
    - 具体値は設計文書の System_CSV マッピング表に従う
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.8_
  - [ ]* 3.2 System_CSV のモード・タグ整合性テストを作成する
    - `scripts/tests/test_csv_migration.py` を新規作成
    - **Property 10: System_CSVのモード・タグ整合性**
    - **Validates: Requirements 7.2, 7.3**

- [x] 4. job_functions.sh の更新
  - [x] 4.1 `parse_list_csv_line` を6カラム対応に変更する
    - 引数を6つ（system, enable, nodes, numproc_node, nthreads, elapse）に変更
    - エクスポート変数: csv_system, csv_enable, csv_nodes, csv_numproc_node, csv_nthreads, csv_elapse
    - ヘッダ行（`system`で始まる）はスキップ（return 1）
    - enable=no → スキップ（return 1）
    - enable が yes/no 以外 → stderr に警告出力しスキップ（return 1）
    - _Requirements: 1.3, 2.1, 2.2, 2.3, 2.4, 8.1, 8.8_
  - [x] 4.2 System_CSV 検索関数群を追加する
    - `get_system_mode`: システム名から mode を返す
    - `get_system_queue_group`: システム名から queue_group を返す
    - `get_system_tag_build`: システム名から tag_build を返す（native時は空文字）
    - `get_system_tag_run`: システム名から tag_run を返す
    - 存在しないシステム名の場合は空文字を返す（exit code 0）
    - _Requirements: 7.5, 7.6, 8.3, 8.4_

  - [ ]* 4.3 parse_list_csv_line の6カラムパースのプロパティベーステストを作成する
    - `scripts/tests/test_job_functions.py` を新規作成
    - **Property 1: parse_list_csv_lineの6カラムパース正当性**
    - **Validates: Requirements 1.3, 8.1, 8.9**
  - [ ]* 4.4 enable フィルタリングのプロパティベーステストを作成する
    - **Property 2: enableフィルタリング**
    - **Validates: Requirements 2.2, 2.3, 8.2**
  - [ ]* 4.5 不正な enable 値の拒否のプロパティベーステストを作成する
    - **Property 3: 不正なenable値の拒否**
    - **Validates: Requirements 2.4**
  - [ ]* 4.6 System_CSV からの mode/tag/queue_group 検索のプロパティベーステストを作成する
    - **Property 11: System_CSVからのmode/tag/queue_group検索**
    - **Validates: Requirements 7.5, 7.6, 8.3, 8.4**

- [x] 5. チェックポイント - job_functions.sh と System_CSV の動作確認
  - 全テストが通ることを確認し、不明点があればユーザーに質問する

- [x] 6. matrix_generate.sh の新CSV形式対応
  - [x] 6.1 `scripts/matrix_generate.sh` の List_CSV 読み込みを6カラム対応に変更する
    - `while IFS=, read -r` の変数を6カラムに変更
    - `parse_list_csv_line` の呼び出しを6引数に変更
    - enable フィルタリングは parse_list_csv_line 内で処理
    - _Requirements: 8.1, 8.2, 8.8_
  - [x] 6.2 mode/tag/queue_group の取得を System_CSV 検索関数に置き換える
    - 旧 `awk -F, -v s="$system" '$1==s && $3=="build"` のタグ検索を `get_system_tag_build` / `get_system_tag_run` に置換
    - mode を `get_system_mode` で取得
    - queue_group を `get_system_queue_group` で取得
    - `get_queue_template` は queue 値を System_CSV から取得するよう更新
    - _Requirements: 8.3, 8.4, 8.5, 8.6, 8.7_
  - [ ]* 6.3 YAML生成のモード別ジョブ構造のプロパティベーステストを作成する
    - **Property 12: YAML生成のモード別ジョブ構造**
    - **Validates: Requirements 8.5, 8.6**

- [x] 7. List_CSV ファイルのマイグレーション
  - [x] 7.1 `programs/qws/list.csv` を新6カラム形式にマイグレーションする
    - ヘッダ: `system,enable,nodes,numproc_node,nthreads,elapse`
    - アクティブ行 → enable=yes、コメント行 → enable=no
    - nodes, numproc_node, nthreads, elapse の値は保持
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.5, 2.6, 2.7_
  - [x] 7.2 `programs/genesis/list.csv` を新6カラム形式にマイグレーションする
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.5, 2.6, 2.7_
  - [x] 7.3 `programs/genesis-nonbonded-kernels/list.csv` を新6カラム形式にマイグレーションする
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.5, 2.6, 2.7_
  - [x] 7.4 `programs/LQCD_dw_solver/list.csv` を新6カラム形式にマイグレーションする
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.5, 2.6, 2.7_
  - [x] 7.5 `programs/scale-letkf/list.csv` を新6カラム形式にマイグレーションする
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.5, 2.6, 2.7_

- [x] 8. Run_Script の引数ベース化
  - [x] 8.1 `programs/genesis/run.sh` から List_CSV 読み込みを削除し、4引数ベースに変更する
    - `$1=system, $2=nodes, $3=numproc_node, $4=nthreads`
    - `while IFS=, read -r ... done < list.csv` ブロックを削除
    - numproc = numproc_node × nodes、totalcores = numproc × nthreads を引数から算出
    - FOM出力ロジックは変更しない
    - _Requirements: 3.1, 3.2, 3.3, 3.7_
  - [x] 8.2 `programs/genesis-nonbonded-kernels/run.sh` から List_CSV 読み込みを削除し、4引数ベースに変更する
    - `$1=system, $2=nodes, $3=numproc_node, $4=nthreads`
    - `while IFS=, read -r ... done < list.csv` ブロックを削除
    - numproc = numproc_node × nodes を引数から算出
    - FOM出力ロジックは変更しない
    - _Requirements: 3.4, 3.5, 3.6, 3.8_
  - [ ]* 8.3 numproc/totalcores 算術導出のプロパティベーステストを作成する
    - **Property 4: numproc/totalcoresの算術導出**
    - **Validates: Requirements 3.3, 3.6**

- [x] 9. test_submit.sh の新CSV形式対応
  - [x] 9.1 `scripts/test_submit.sh` を新6カラム List_CSV 形式に対応させる
    - カラムパースを6カラム（system, enable, nodes, numproc_node, nthreads, elapse）に変更
    - mode/queue_group/tag 情報を System_CSV 検索関数で取得
    - `source ./scripts/job_functions.sh` を追加
    - ジョブ投入コマンドの引数を更新
    - _Requirements: 8.9, 8.10_

- [x] 10. 最終チェックポイント - 全体の統合確認
  - 全テストが通ることを確認し、不明点があればユーザーに質問する

## 備考

- `*` マーク付きのタスクはオプションであり、スキップ可能
- 各タスクは具体的な要件番号を参照しトレーサビリティを確保
- チェックポイントで段階的に動作を検証
- プロパティベーステストは Python (Hypothesis) + subprocess でシェル関数を呼び出す形式
- テストファイルは `scripts/tests/` ディレクトリに配置
