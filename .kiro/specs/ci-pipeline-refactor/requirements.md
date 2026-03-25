# 要件文書: CI基盤リファクタリングと堅牢化

## はじめに

本文書は、CIパイプライン基盤のリファクタリングと堅牢化に関する要件を定義する。主な目的は以下の通り:

1. list.csvからmode/queue_groupカラムを廃止し、システム設定（system.csv）に責任を集約する
2. enableカラムの導入によるジョブ有効/無効の明示的管理
3. run.sh内のlist.csv読み込みを廃止し、引数ベースのインターフェースに統一する
4. FOM/SECTION/OVERLAP出力を標準化する共通関数群（bk_functions.sh）を作成する
5. system.csvおよびmatrix_generate.shを新しいCSV形式に対応させる

## 用語集

- **List_CSV**: 各プログラムディレクトリ（`programs/*/list.csv`）に配置されるCSVファイル。ベンチマーク実行構成（システム名、ノード数、プロセス数等）を定義する
- **System_CSV**: `config/system.csv` に配置されるCSVファイル。システムごとのタグ、ロール、キュー、実行モード等を定義する
- **Queue_CSV**: `config/queue.csv` に配置されるCSVファイル。キュー名とジョブ投入テンプレートを定義する
- **Matrix_Generator**: `scripts/matrix_generate.sh`。List_CSVとSystem_CSVを読み込み、GitLab CI用の動的YAMLを生成するスクリプト
- **Run_Script**: 各プログラムの `programs/*/run.sh`。ベンチマーク実行を行うスクリプト
- **BK_Functions**: `scripts/bk_functions.sh` に配置される共通関数ライブラリ。FOM出力等の標準化関数を提供する
- **Job_Functions**: `scripts/job_functions.sh` に配置される既存の共通関数ライブラリ。CSVパース等の関数を提供する
- **Result_Parser**: `scripts/result.sh`。Run_Scriptの出力（FOM行、SECTION行、OVERLAP行）をパースしてJSON形式に変換するスクリプト
- **Test_Submit**: `scripts/test_submit.sh`。手動テスト投入用スクリプト
- **FOM**: Figure of Merit。ベンチマーク性能指標値
- **SECTION**: FOMの内訳を構成する時間区間（例: compute_kernel, communication）
- **OVERLAP**: 複数SECTIONが重複する時間区間
- **mode**: ビルドと実行の方式を示す値。`cross`（ビルドと実行が別ノード）または `native`（同一ノードでビルドと実行）
- **queue_group**: ジョブスケジューラに投入する際のキューグループ名（例: small, debug-g）
- **enable**: ジョブ構成の有効/無効を示すカラム値。`yes` または `no`

## 要件

### 要件1: List_CSVからmode/queue_groupカラムを廃止する

**ユーザーストーリー:** 開発者として、List_CSVからmode/queue_groupカラムを削除したい。これにより、実行モードとキューグループの管理をSystem_CSVに一元化し、各プログラムのCSV管理を簡素化できる。

#### 受入基準

1. THE List_CSV SHALL have the header format `system,enable,nodes,numproc_node,nthreads,elapse` (6 columns)
2. THE List_CSV SHALL NOT contain `mode` or `queue_group` columns
3. WHEN a List_CSV file is read, THE Job_Functions SHALL parse 6 columns: system, enable, nodes, numproc_node, nthreads, elapse
4. THE List_CSV for each program (genesis, genesis-nonbonded-kernels, qws, LQCD_dw_solver, scale-letkf) SHALL be updated to the new 6-column format
5. WHEN the List_CSV is migrated, THE existing configuration values for nodes, numproc_node, nthreads, elapse SHALL be preserved unchanged

### 要件2: enableカラムの追加

**ユーザーストーリー:** 開発者として、List_CSVにenableカラムを追加したい。これにより、`#`コメントアウトに代わる明示的なジョブ有効/無効管理が可能になる。

#### 受入基準

1. THE List_CSV SHALL contain an `enable` column as the second column with values `yes` or `no`
2. WHEN a List_CSV line has enable value `yes`, THE Matrix_Generator SHALL include the line in job generation
3. WHEN a List_CSV line has enable value `no`, THE Matrix_Generator SHALL skip the line
4. WHEN a List_CSV line has an enable value other than `yes` or `no`, THE Job_Functions SHALL treat the line as invalid and skip the line with a warning message to stderr
5. THE List_CSV SHALL NOT use `#` comment-out lines for disabling job configurations
6. WHEN migrating existing List_CSV files, THE previously commented-out lines (prefixed with `#`) SHALL be converted to lines with enable value `no`
7. WHEN migrating existing List_CSV files, THE previously active lines SHALL be converted to lines with enable value `yes`

### 要件3: Run_Script内のList_CSV読み込みの廃止

**ユーザーストーリー:** 開発者として、genesis/run.shとgenesis-nonbonded-kernels/run.shからList_CSV読み込みロジックを削除したい。これにより、Run_Scriptのインターフェースが引数ベースに統一され、保守性が向上する。

#### 受入基準

1. THE genesis Run_Script SHALL accept 4 positional arguments: system, nodes, numproc_node, nthreads
2. THE genesis Run_Script SHALL NOT read List_CSV files
3. THE genesis Run_Script SHALL derive numproc and totalcores from the positional arguments (numproc = numproc_node × nodes, totalcores = numproc × nthreads)
4. THE genesis-nonbonded-kernels Run_Script SHALL accept 4 positional arguments: system, nodes, numproc_node, nthreads
5. THE genesis-nonbonded-kernels Run_Script SHALL NOT read List_CSV files
6. THE genesis-nonbonded-kernels Run_Script SHALL derive numproc from the positional arguments (numproc = numproc_node × nodes)
7. WHEN the genesis Run_Script is invoked with 4 arguments, THE Run_Script SHALL produce the same FOM output as the current implementation
8. WHEN the genesis-nonbonded-kernels Run_Script is invoked with 4 arguments, THE Run_Script SHALL produce the same FOM output as the current implementation


### 要件4: bk_emit_result関数の作成

**ユーザーストーリー:** 開発者として、FOM出力を標準化するbk_emit_result関数を作成したい。これにより、各Run_ScriptでのFOM出力形式のばらつきを解消し、Result_Parserとの整合性を保証できる。

#### 受入基準

1. THE BK_Functions SHALL provide a `bk_emit_result` function in `scripts/bk_functions.sh`
2. THE `bk_emit_result` function SHALL accept named arguments: `--fom`, `--fom-version`, `--exp`, `--nodes`, `--numproc-node`, `--nthreads`
3. THE `bk_emit_result` function SHALL require the `--fom` argument as mandatory
4. WHEN `--fom` is not provided, THE `bk_emit_result` function SHALL print an error message to stderr and return exit code 1
5. WHEN `--fom` is provided with a non-numeric value, THE `bk_emit_result` function SHALL print an error message to stderr and return exit code 1
6. WHEN all required arguments are valid, THE `bk_emit_result` function SHALL output a single line in the format: `FOM:<value> FOM_version:<version> Exp:<experiment> node_count:<nodes> numproc_node:<numproc_node> nthreads:<nthreads>`
7. WHEN optional arguments are omitted, THE `bk_emit_result` function SHALL omit the corresponding key-value pairs from the output line
8. THE BK_Functions SHALL NOT depend on jq or other non-POSIX tools
9. THE `bk_emit_result` output format SHALL be compatible with the existing Result_Parser (`scripts/result.sh`) parsing logic

### 要件5: bk_emit_section関数の作成

**ユーザーストーリー:** 開発者として、SECTION出力を標準化するbk_emit_section関数を作成したい。これにより、FOM内訳の出力形式を統一し、Result_Parserとの整合性を保証できる。

#### 受入基準

1. THE BK_Functions SHALL provide a `bk_emit_section` function in `scripts/bk_functions.sh`
2. THE `bk_emit_section` function SHALL accept 2 positional arguments: section name and time value
3. WHEN the section name argument is missing, THE `bk_emit_section` function SHALL print an error message to stderr and return exit code 1
4. WHEN the time value argument is missing, THE `bk_emit_section` function SHALL print an error message to stderr and return exit code 1
5. WHEN the time value is not a valid number, THE `bk_emit_section` function SHALL print an error message to stderr and return exit code 1
6. WHEN both arguments are valid, THE `bk_emit_section` function SHALL output a single line in the format: `SECTION:<name> time:<time>`
7. THE `bk_emit_section` output format SHALL be compatible with the existing Result_Parser (`scripts/result.sh`) SECTION parsing logic

### 要件6: bk_emit_overlap関数の作成

**ユーザーストーリー:** 開発者として、OVERLAP出力を標準化するbk_emit_overlap関数を作成したい。これにより、セクション重複時間の出力形式を統一し、Result_Parserとの整合性を保証できる。

#### 受入基準

1. THE BK_Functions SHALL provide a `bk_emit_overlap` function in `scripts/bk_functions.sh`
2. THE `bk_emit_overlap` function SHALL accept 2 positional arguments: comma-separated section names and time value
3. WHEN the section names argument is missing, THE `bk_emit_overlap` function SHALL print an error message to stderr and return exit code 1
4. WHEN the time value argument is missing, THE `bk_emit_overlap` function SHALL print an error message to stderr and return exit code 1
5. WHEN the time value is not a valid number, THE `bk_emit_overlap` function SHALL print an error message to stderr and return exit code 1
6. WHEN both arguments are valid, THE `bk_emit_overlap` function SHALL output a single line in the format: `OVERLAP:<section_names> time:<time>`
7. THE `bk_emit_overlap` output format SHALL be compatible with the existing Result_Parser (`scripts/result.sh`) OVERLAP parsing logic

### 要件7: System_CSVの1システム1行形式への再設計

**ユーザーストーリー:** 開発者として、System_CSVを1システム1行形式に再設計し、mode/tag_build/tag_run/queue/queue_groupを統合管理したい。これにより、システム設定の見通しが良くなり、modeに応じたタグの使い分けが明確になる。

#### 受入基準

1. THE System_CSV SHALL have the header format `system,mode,tag_build,tag_run,queue,queue_group`
2. THE System_CSV SHALL contain exactly one row per system
3. WHEN mode is `cross`, THE System_CSV SHALL have non-empty values for both tag_build and tag_run
4. WHEN mode is `native`, THE System_CSV SHALL have an empty tag_build and a non-empty tag_run
5. THE Matrix_Generator SHALL read mode, tag_build, tag_run, queue, and queue_group from System_CSV for each system
6. WHEN mode is `cross`, THE Matrix_Generator SHALL use tag_build for the build job and tag_run for the run job
7. WHEN mode is `native`, THE Matrix_Generator SHALL use tag_run for the combined build_run job
8. THE System_CSV mode, tag, and queue_group values SHALL be consistent with the values previously defined in the old System_CSV and List_CSV files for each system

### 要件8: Matrix_Generatorの新CSV形式対応

**ユーザーストーリー:** 開発者として、Matrix_Generatorを新しいCSV形式に対応させたい。これにより、enableカラムによるフィルタリングとSystem_CSVからのmode/tag/queue_group取得が正しく動作する。

#### 受入基準

1. THE Matrix_Generator SHALL read List_CSV files with the new 6-column format (system, enable, nodes, numproc_node, nthreads, elapse)
2. THE Matrix_Generator SHALL skip lines where enable is `no`
3. THE Matrix_Generator SHALL read mode, tag_build, tag_run, queue, and queue_group from System_CSV for each system (1 row per system)
4. WHEN mode is `cross`, THE Matrix_Generator SHALL generate separate build and run jobs using tag_build and tag_run respectively
5. WHEN mode is `native`, THE Matrix_Generator SHALL generate a combined build_run job using tag_run
6. THE Matrix_Generator SHALL export queue_group as an environment variable for template expansion in Queue_CSV
7. THE generated YAML SHALL be functionally equivalent to the current output for the same set of enabled configurations
8. THE Job_Functions `parse_list_csv_line` function SHALL be updated to parse the new 6-column format (system, enable, nodes, numproc_node, nthreads, elapse)
9. THE Test_Submit script SHALL be updated to parse the new 6-column List_CSV format and read mode/tag/queue_group from System_CSV
