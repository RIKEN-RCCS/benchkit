# 要件ドキュメント

## はじめに

crossモードのCIパイプラインにおいて、同一の code+system の組み合わせに対して複数の実験設定（ノード数、プロセス数、スレッド数が異なる）が `list.csv` に定義されている場合、buildジョブが実験ごとに重複生成される問題を解決する。

現状、`scale-letkf/list.csv` に Fugaku cross で N3 と N75 の2行がある場合、`scale-letkf_Fugaku_N3_P4_T12_build` と `scale-letkf_Fugaku_N75_P4_T12_build` の2つのbuildジョブが生成される。しかし、buildスクリプトは `bash programs/scale-letkf/build.sh Fugaku` を実行するだけで、ノード数・プロセス数・スレッド数はビルドに無関係である。buildは code+system ごとに1回だけ実行し、複数のrunジョブがその単一のbuildジョブに依存する構造にすべきである。

## 用語集

- **Matrix_Generator**: `scripts/matrix_generate.sh` スクリプト。`list.csv` を読み取り、GitLab CI の YAML ファイル（`.gitlab-ci.generated.yml`）を生成するシステム
- **Build_Job**: crossモードにおいて、プログラムのビルドを実行するCIジョブ。`build.sh` スクリプトを呼び出す
- **Run_Job**: crossモードにおいて、ビルド済みのプログラムを実行するCIジョブ。`run.sh` スクリプトを呼び出す
- **Experiment_Config**: `list.csv` の1行に対応する実験設定。system, mode, queue_group, nodes, numproc_node, nthreads, elapse の組み合わせ
- **Code_System_Pair**: プログラム名（code）とシステム名（system）の組み合わせ。buildジョブの一意性を決定する単位
- **Cross_Mode**: ビルドとランを異なるノード（タグ）で実行するモード。build と run が別ジョブとして生成される
- **Native_Mode**: ビルドとランを同一ノードで実行するモード。build_run として1つのジョブで生成される（本変更の対象外）
- **Job_Prefix**: ジョブ名の接頭辞。現状は `{program}_{system}_N{nodes}_P{numproc_node}_T{nthreads}` 形式
- **Build_Key**: buildジョブの重複排除に使用するキー。`{program}_{system}` の形式

## 要件

### 要件 1: crossモードのbuildジョブ重複排除

**ユーザーストーリー:** CIパイプラインの管理者として、同一 code+system に対するbuildジョブを1回だけ実行したい。これにより、不要なビルドの重複実行を排除し、パイプラインの実行時間とリソース消費を削減できる。

#### 受け入れ基準

1. WHEN 同一の Code_System_Pair に対して複数の Experiment_Config が list.csv に存在する場合、THE Matrix_Generator SHALL 当該 Code_System_Pair に対して Build_Job を1つだけ生成する
2. WHEN 同一の Code_System_Pair に対して Build_Job が1つだけ生成された場合、THE Matrix_Generator SHALL 当該 Code_System_Pair の全ての Run_Job が同一の Build_Job に依存（needs）するよう YAML を生成する
3. THE Matrix_Generator SHALL Build_Job のジョブ名を `{program}_{system}_build` の形式で生成する（実験パラメータを含めない）
4. WHEN Code_System_Pair に対して Experiment_Config が1つだけ存在する場合、THE Matrix_Generator SHALL 従来通り Build_Job を1つ、Run_Job を1つ生成する

### 要件 2: Run_Job のジョブ名とbuild依存関係

**ユーザーストーリー:** CIパイプラインの管理者として、各 Run_Job が正しいbuildジョブに依存し、かつ実験設定ごとに一意に識別可能なジョブ名を持つようにしたい。

#### 受け入れ基準

1. THE Matrix_Generator SHALL Run_Job のジョブ名を `{program}_{system}_N{nodes}_P{numproc_node}_T{nthreads}_run` の形式で維持する
2. THE Matrix_Generator SHALL 各 Run_Job の needs フィールドに `{program}_{system}_build` を指定する
3. THE Matrix_Generator SHALL 各 Run_Job の後続ジョブ（send_results, estimate, send_estimate）の依存関係を正しく維持する

### 要件 3: ステージ分離と並列実行

**ユーザーストーリー:** CIパイプラインの管理者として、GitLabのパイプライン画面上で build(cross)、build_run(native)、run(cross) を別カラムとして視覚的に区別したい。同時に、ステージ間の不要な待ちを排除し、依存関係が満たされたジョブは即座に開始されるようにしたい。

#### 受け入れ基準

1. THE Matrix_Generator SHALL stages を `build, build_run, run, send_results, estimate, send_estimate` の順で定義する（build と build_run を別ステージとする）
2. THE Matrix_Generator SHALL nativeモードの build_run ジョブを `build_run` ステージに配置する
3. THE Matrix_Generator SHALL nativeモードの build_run ジョブに `needs: []` を指定し、build ステージの完了を待たずに即座に開始可能とする
4. WHEN Experiment_Config の mode が "native" の場合、THE Matrix_Generator SHALL 従来通り `{job_prefix}_build_run` 形式のジョブを生成する（ジョブ内容は変更しない）
5. THE Matrix_Generator SHALL crossモードの Run_Job に `needs: ["{program}_{system}_build"]` を指定し、対応する Build_Job 完了後に即座に開始可能とする（他の Build_Job の完了を待たない）

### 要件 4: 後続ジョブチェーンの正確性

**ユーザーストーリー:** CIパイプラインの管理者として、buildジョブの重複排除後も、send_results・estimate・send_estimate の各ジョブが正しい依存関係で生成されることを保証したい。

#### 受け入れ基準

1. THE Matrix_Generator SHALL 各 Experiment_Config に対して send_results ジョブを生成し、対応する Run_Job に依存させる
2. WHEN estimate 対象のシステムかつ estimate.sh が存在する場合、THE Matrix_Generator SHALL 各 Experiment_Config に対して estimate ジョブと send_estimate ジョブを生成する
3. THE Matrix_Generator SHALL send_results ジョブ名を `{program}_{system}_N{nodes}_P{numproc_node}_T{nthreads}_send_results` の形式で生成する

### 要件 5: buildジョブの重複検出メカニズム

**ユーザーストーリー:** 開発者として、buildジョブの重複排除が確実に動作する仕組みを持ちたい。

#### 受け入れ基準

1. THE Matrix_Generator SHALL Code_System_Pair ごとにbuildジョブの生成済みフラグを管理する
2. WHEN 同一の Code_System_Pair に対する2回目以降の Experiment_Config を処理する場合、THE Matrix_Generator SHALL Build_Job の YAML 出力をスキップする
3. THE Matrix_Generator SHALL buildジョブの重複検出に連想配列またはそれに相当するメカニズムを使用する
