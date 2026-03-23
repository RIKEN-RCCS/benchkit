# 要件定義書

## はじめに

result_serverのサマリーテーブル（`_results_table.html`）に対するUX改善を行う。
Compareカラムの位置変更とツールチップ修正、Expフィルタのカスケード連動、Proc/nodeカラムの追加、Thread/procカラムの追加（result.shでのFOM行パースを含む）、ハードスペック系カラムの削除を実装する。

## 用語集

- **Results_Table**: ベンチマーク結果を一覧表示するHTMLテーブルコンポーネント（`_results_table.html`）
- **Filter_Dropdowns**: System/Code/Expのサーバーサイドフィルタリング用ドロップダウンUI（`_filter_dropdowns.html`）
- **Results_Loader**: JSONファイルからテーブルデータを読み込み、行・カラム・フィルタオプションを構築するPythonモジュール（`results_loader.py`）
- **Results_Route**: HTTPリクエストを処理し、フィルタパラメータの抽出・データ読み込み・テンプレートレンダリングを行うFlaskルート（`results.py`）
- **Compare_Column**: 結果比較用チェックボックスを含むテーブルカラム
- **Cascade_Filter**: 親フィルタの選択値に基づいて子フィルタの選択肢を動的に絞り込む連動フィルタ機構
- **Result_JSON**: ベンチマーク実行結果を格納するJSONファイル。`code`, `system`, `Exp`, `node_count`, `numproc_node`, `nthreads` 等のフィールドを持つ
- **Result_Script**: ベンチマーク実行後にFOM行をパースしResult_JSONを生成するシェルスクリプト（`result.sh`）
- **FOM行**: results/resultファイル内の `FOM:` で始まる行。`FOM:`, `node_count:`, `numproc_node:`, `nthreads:`, `Exp:` 等のキーバリューペアを含む

## 要件

### 要件 1: Compareカラムの位置変更

**ユーザーストーリー:** ベンチマーク結果を閲覧するユーザーとして、Compareチェックボックスカラムをテーブル左端ではなくFOMカラムの右隣に配置してほしい。これにより、ツールチップが画面外に見切れる問題が解消され、関連データを確認しながら比較対象を選択できる。

#### 受け入れ基準

1. THE Results_Table SHALL Compareカラムをテーブルヘッダーにおいて、FOMカラムの直後（右隣）に表示する
2. THE Results_Table SHALL Compareカラムのチェックボックスセルを、各データ行においてFOMセルの直後（右隣）に表示する
3. THE Results_Table SHALL Compareカラムのツールチップに `tooltip-left` ではないデフォルトの方向指定を使用し、ツールチップが画面内に収まるようにする
4. WHEN ユーザーがCompareチェックボックスを操作した場合、THE Results_Table SHALL 既存の比較機能（Select All Visible、Deselect All、Compare遷移）を変更なく動作させる

### 要件 2: Expフィルタのカスケード連動

**ユーザーストーリー:** ベンチマーク結果を分析するユーザーとして、Codeフィルタを選択した際にExpドロップダウンの選択肢がそのCodeに紐づくExpのみに絞り込まれてほしい。これにより、大量のExp選択肢から目的のものを探す手間が省ける。

#### 受け入れ基準

1. WHEN Codeフィルタが選択されている場合、THE Results_Loader SHALL Expフィルタの選択肢を、選択されたCodeを持つResult_JSONに含まれるExp値のみに絞り込む
2. WHEN Codeフィルタが未選択（All）の場合、THE Results_Loader SHALL Expフィルタの選択肢として全てのExp値を返す
3. THE Results_Route SHALL Codeフィルタの値を `get_filter_options` 関数に渡し、カスケードフィルタリングを実行する
4. WHEN Codeフィルタの値が変更された場合、THE Filter_Dropdowns SHALL ページをリロードし、サーバーサイドで絞り込まれたExpの選択肢を表示する
5. WHEN Codeフィルタが変更され、現在選択中のExpが新しい選択肢に含まれない場合、THE Filter_Dropdowns SHALL Expフィルタの選択を「All」にリセットする

### 要件 3: Proc/nodeカラムの追加

**ユーザーストーリー:** ベンチマーク結果を分析するユーザーとして、ノード当たりのプロセス数（Proc/node）をテーブルで確認したい。これにより、実行構成の詳細をテーブル上で把握できる。

#### 受け入れ基準

1. THE Results_Loader SHALL カラムリストに `("Proc/node", "numproc_node")` を `("Nodes", "nodes")` の直後に追加する
2. THE Results_Loader SHALL `_build_row` でResult_JSONの `numproc_node` フィールドから値を取得し、フィールドが存在しないかNullか空文字列の場合は `"N/A"` をフォールバック値として使用する
3. THE Results_Table SHALL Proc/nodeカラムのヘッダーにツールチップ「Number of processes per node」を表示する
4. THE Results_Table SHALL 各データ行にProc/nodeの値を表示する
5. WHEN `numproc_node` フィールドがResult_JSONに存在しない場合、THE Results_Table SHALL 該当セルに `"N/A"` を表示する

### 要件 4: Thread/procカラムの追加

**ユーザーストーリー:** ベンチマーク結果を分析するユーザーとして、プロセス当たりのスレッド数（Thread/proc）をテーブルで確認したい。これにより、並列実行構成の詳細をテーブル上で把握できる。

#### 受け入れ基準

1. THE Results_Loader SHALL カラムリストに `("Thread/proc", "nthreads")` を `("Proc/node", "numproc_node")` の直後に追加する
2. THE Results_Loader SHALL `_build_row` でResult_JSONの `nthreads` フィールドから値を取得し、フィールドが存在しないかNullか空文字列の場合は `"N/A"` をフォールバック値として使用する
3. THE Results_Table SHALL Thread/procカラムのヘッダーにツールチップ「Number of threads per process」を表示する
4. THE Results_Table SHALL 各データ行にThread/procの値を表示する
5. WHEN `nthreads` フィールドがResult_JSONに存在しない場合、THE Results_Table SHALL 該当セルに `"N/A"` を表示する
6. THE Result_Script SHALL FOM行から `nthreads:` をパースし、Result_JSONの `nthreads` フィールドに記録する（`numproc_node` と同じパターン: `grep -Eo 'nthreads:[ ]*[0-9]*'`）
7. IF FOM行に `nthreads:` が含まれない場合、THEN THE Result_Script SHALL `nthreads` フィールドに空文字列を記録する

### 要件 5: ハードスペック系カラムの削除

**ユーザーストーリー:** ベンチマーク結果を閲覧するユーザーとして、CPU Name、GPU Name、CPU/node、GPU/node、CPU Core Countのカラムをテーブルから削除してほしい。これらの情報はSYSTEMカラムのツールチップで既に表示されており、テーブルの横幅を不必要に広げている。

#### 受け入れ基準

1. THE Results_Loader SHALL カラムリストから `("CPU Name", "cpu")`, `("GPU Name", "gpu")`, `("CPU/node", "cpus")`, `("GPU/node", "gpus")`, `("CPU Core Count", "cpu_cores")` を削除する
2. THE Results_Loader SHALL `_build_row` から `cpu_name`, `gpu_name`, `cpus_per_node`, `gpus_per_node`, `cpu_cores` フィールドの抽出コードを削除する
3. THE Results_Table SHALL SYSTEMカラムのツールチップにCPU Name、CPU/node、CPU Cores、GPU Name、GPU/node、Memoryの情報を引き続き表示する
4. WHEN テーブルが描画された場合、THE Results_Table SHALL ハードスペック系カラムのヘッダーおよびデータセルを表示しない
