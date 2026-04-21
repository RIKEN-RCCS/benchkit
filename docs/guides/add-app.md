# アプリ追加手順（開発者向け）

このドキュメントは、BenchKit に新しいアプリ（プログラム）を追加する手順を開発者向けにまとめたものです。
サンプルアプリ `qws` を参考に、新しいアプリ `<code>` を追加して PR を作成するまでを説明します。

## 目次

1. [リポジトリの準備](#1-リポジトリの準備)
2. [アプリの基本構成](#2-アプリの基本構成)
3. [設定ファイルの作成](#3-設定ファイルの作成)
4. [ビルドスクリプトの作成](#4-ビルドスクリプトの作成)
5. [実行スクリプトの作成](#5-実行スクリプトの作成)
6. [ローカルテスト](#6-ローカルテスト)
7. [バッチジョブテスト](#7-バッチジョブテスト)
8. [PR作成](#8-pr作成)

---

## 1. リポジトリの準備

### Fork と Clone
```bash
# GitHub で https://github.com/RIKEN-RCCS/benchkit を Fork
git clone https://github.com/<yourname>/benchkit.git
cd benchkit
```

### 作業用ブランチの作成
```bash
git checkout -b add-<code>
# 例: git checkout -b add-myapp
```

---

## 2. アプリの基本構成

### ディレクトリ構成
```
programs/<code>/
├── build.sh    # ビルドスクリプト
├── run.sh      # 実行スクリプト
└── list.csv    # 実行条件定義
```

### サンプルのコピー
```bash
cp -pr programs/qws/ programs/<code>
cd programs/<code>
```

---

## 3. 設定ファイルの作成

### `list.csv` - 実行条件定義
同一システムで異なるノード数・プロセス数の組み合わせを定義可能：

```csv
system,enable,nodes,numproc_node,nthreads,elapse
# Fugaku での複数設定例
Fugaku,yes,1,4,12,0:10:00
Fugaku,yes,2,4,12,0:20:00
# MiyabiG/MiyabiC での設定例
MiyabiG,yes,1,1,72,0:10:00
MiyabiC,yes,1,1,112,0:10:00
# RC系での設定例
RC_DGXSP,yes,1,1,20,0:10:00
RC_GENOA,yes,1,1,96,0:10:00
RC_FX700,yes,1,4,12,0:10:00
# ログインノードでのテスト用
FugakuLN,yes,1,1,1,0:10:00
```

**パラメータ説明：**
- `system`: 実行システム名（config/system.csvと対応）
- `enable`: ジョブの有効/無効（`yes` または `no`）
- `nodes`: ノード数
- `numproc_node`: ノードあたりプロセス数
- `nthreads`: スレッド数
- `elapse`: 実行時間制限

> **Note**: `list.csv` は「アプリごとの実験条件」だけを書くファイルです。`mode` と `queue_group` は `config/system.csv` で一元管理されるため、list.csv には含めません。ジョブを無効化するには `enable=no` を設定します（`#` コメントアウトは使用しません）。

### `config/system.csv` との責務分担

BenchKit では、実行条件とシステム運用設定を明確に分けます。

- `programs/<code>/list.csv`
  - そのアプリをどのシステム・どのノード数・どのMPI/OpenMP条件で流すか
  - アプリごとに変わる条件を書く
- `config/system.csv`
  - `mode`、Runner tag、`queue`、`queue_group` など、そのシステムで共通な運用設定を書く
  - 全アプリで共有される条件を書く
- `config/system_info.csv`
  - Result Server や `/systemlist` に出すシステム表示情報を書く
  - アプリ開発者が、その system が portal 上でどう見えるかを確認するときの正本になる

新しい system を `list.csv` に追加する前に、`config/system.csv` と `config/system_info.csv` の両方に対象 system があるかを確認しておくと、実行条件と portal 表示のずれを減らせる。

この分担により、同じシステムに対して各アプリが `mode` や `queue_group` を重複定義する必要がなくなります。

### `source_info` の現時点の方針

BenchKit では、まず **top-level application の source provenance** を追えることを優先します。
具体的には、Git 管理のアプリであれば `repo_url`、`branch`、`commit_hash` を `source_info` として入れられる形が望ましいです。

一方で、ローカルファイルや依存ライブラリを含む完全な provenance を、現時点ですべての app に必須化する方針ではありません。
portal の `/results/usage` では、この source provenance が各 app / system の最新 result に対して current-state として見えるので、まずは top-level source tracked を目標に整備すると自然です。

---

## 4. ビルドスクリプトの作成

### `build.sh` の基本構造
```bash
#!/bin/bash
set -e
system="$1"
mkdir -p artifacts

# ソースコード取得
git clone https://github.com/your-org/your-app.git
cd your-app

# システム別ビルド設定
case "$system" in
    Fugaku)
        # A64FX向けクロスコンパイル
        make -j 8 compiler=fujitsu_cross mpi=1
        ;;
    FugakuCN)
        # A64FX向けネイティブコンパイル
        make -j 8 compiler=fujitsu_native mpi=1
        ;;
    FugakuLN)
        # x86_64向けビルド（テスト用）
        make -j 2 compiler=gnu arch=skylake mpi=
        ;;
    MiyabiG)
        # Neoverse-N1向けビルド
        make -j 8 compiler=openmpi-gnu arch=skylake mpi=1
        ;;
    MiyabiC)
        # Intel向けビルド
        make -j 8 compiler=intel arch=skylake mpi=1
        ;;
    RC_GENOA)
        # AMD Genoa向けビルド
        module load system/genoa mpi/openmpi-x86_64
        make -j 8 compiler=openmpi-gnu arch=skylake mpi=1
        ;;
    RC_DGXSP)
        # DGX Spark向けビルド
        source /etc/profile.d/modules.sh
        module load system/ng-dgx nvhpc-hpcx/26.3
        make -j 8 compiler=openmpi-gnu arch=skylake mpi=1
        ;;
    RC_FX700)
        # A64FX系FX700向けビルド
        module load system/fx700 FJSVstclanga
        make -j 8 compiler=fujitsu_native mpi=1 SYSLIBS=
        ;;
    *)
        echo "Unknown system: $system"
        exit 1
        ;;
esac

# 実行ファイルをartifactsに保存
cp your-app_main_executable ../artifacts/
```

### qwsの実際の例
```bash
# Fugaku向けA64FXクロスコンパイル
make -j 8 fugaku_benchmark= omp=1 compiler=fujitsu_cross rdma= mpi=1 powerapi=

# MiyabiG向けNeoverse-N1ビルド
make -j 8 fugaku_benchmark= omp=1 compiler=openmpi-gnu arch=skylake rdma= mpi=1 powerapi=

# FX700向けA64FXネイティブビルド
make -j 8 fugaku_benchmark= omp=1 compiler=fujitsu_native rdma= mpi=1 powerapi= SYSLIBS=
```

### ビルドテスト
```bash
# ログインノードでのビルドテスト
bash programs/<code>/build.sh FugakuLN
ls artifacts/  # 実行ファイルが生成されることを確認

# A64FX向けビルド（Fugaku環境）
bash programs/<code>/build.sh Fugaku
ls artifacts/  # クロスコンパイル済み実行ファイルを確認
```

### Artifacts最適化の注意点
CI/CDパイプラインでのartifacts保存を最適化するため、以下の点に注意してください：

**推奨事項：**
- 必要な実行ファイルのみを保存
- ソースコード全体やビルドディレクトリ全体の保存は避ける
- 適切なディレクトリ構造で整理

**例（qwsの場合）：**
```bash
# 良い例：必要なファイルのみ保存
mkdir -p artifacts
cp qws/qws_main_executable artifacts/

# 避けるべき例：ディレクトリ全体の保存
# cp -r qws/ artifacts/  # ソースコード全体は避ける
```

**効果：**
- CI/CDパイプラインの実行時間短縮
- ストレージ使用量の削減
- アーティファクトのアップロード/ダウンロード時間の短縮

---

## 5. 実行スクリプトの作成

### `run.sh` の基本構造
```bash
#!/bin/bash
set -e
system="$1"
nodes="$2"
numproc_node="$3"
nthreads="$4"
export OMP_NUM_THREADS=$nthreads

source "${PWD}/scripts/bk_functions.sh"

mkdir -p results && > results/result

# ソースコード取得（既存ならスキップ）
[[ -d your-app ]] || git clone https://github.com/your-org/your-app.git

# artifactsから実行ファイルをコピー
cp artifacts/qws_main_executable your-app/

cd your-app

case "$system" in
    Fugaku|FugakuCN)
        # MPI実行（富岳）
        mpiexec -n $((nodes * numproc_node)) ./main [args] > output
        # 結果解析
        FOM=$(grep "performance" output | awk '{print $2}')
        bk_emit_result --fom "$FOM" --fom-version v1.0 --exp test \
            --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
        ;;
    FugakuLN)
        # ログインノードでのテスト実行
        export OMP_NUM_THREADS=12
        ./main [args] > output
        FOM=$(grep "performance" output | awk '{print $2}')
        bk_emit_result --fom "$FOM" --fom-version v1.0 --exp test \
            --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
        ;;
    MiyabiG|MiyabiC)
        # MPI実行（Miyabi）
        mpirun -n $((nodes * numproc_node)) ./main [args] > output
        FOM=$(grep "performance" output | awk '{print $2}')
        bk_emit_result --fom "$FOM" --fom-version v1.0 --exp test \
            --nodes "$nodes" --numproc-node "$numproc_node" --nthreads "$nthreads" >> ../results/result
        ;;
    *)
        echo "Unknown system: $system"
        exit 1
        ;;
esac

# NFS同期
cd ..
sync
```


### 結果フォーマット
`results/result` の各行は以下の形式：
```
FOM:5.752 FOM_version:DDSolverJacobi Exp:CASE0 node_count:1 numproc_node:4 nthreads:12
SECTION:compute_kernel time:0.30
SECTION:communication time:0.20
OVERLAP:compute_kernel,communication time:0.05
```

**`bk_functions.sh` の利用（推奨）：**

`scripts/bk_functions.sh` を `source` して、標準化された出力関数を使用してください：

```bash
source "${PWD}/scripts/bk_functions.sh"

# FOM出力
bk_emit_result --fom 5.752 --fom-version DDSolverJacobi --exp CASE0 \
    --nodes 1 --numproc-node 4 --nthreads 12 >> results/result

# FOM内訳（オプション）
bk_emit_section compute_kernel 0.30 >> results/result
bk_emit_section communication 0.20 >> results/result
bk_emit_overlap compute_kernel,communication 0.05 >> results/result
```

**bk_emit_result の引数：**
- `--fom 数値` - 性能指標（必須）
- `--fom-version 文字列` - バージョン情報
- `--exp 文字列` - 実験名
- `--nodes 数値` - ノード数
- `--numproc-node 数値` - ノードあたりプロセス数
- `--nthreads 数値` - プロセスあたりスレッド数
- `--confidential 文字列` - 機密データ（チーム限定表示）

省略された引数は出力に含まれません。`--fom` のみが必須です。

### Performance Analysis データ
詳細データは `results/padata[0-9].tgz` として保存：
```bash
# PAデータの作成例
mkdir -p pa
echo "detailed_data" > pa/analysis.dat
tar -czf ../results/padata0.tgz ./pa
```

### Fugaku で `fapp` を使う場合

Fugaku 系アプリでは、アプリ側が profiler tool を内部で選び、BenchKit 共通の `bk_profiler` helper に渡す形が扱いやすいです。
`bk_profiler` は profiler ごとの raw data / postprocess report をまとめて `results/padata*.tgz` に保存し、archive 内の `bk_profiler_artifact/meta.json` に metadata を入れます。BenchKit や推定 package はこの `meta.json` を見て、tool、level、report kind を機械的に判断できます。

`fapp` では共通 level として次を扱います。

- `single` → `pa1`
- `simple` → `pa1..pa5`
- `standard` → `pa1..pa11`
- `detailed` → `pa1..pa17`

`single` は既定で text summary、`simple/standard/detailed` は既定で text + CSV report を保存します。CSV は `fapp` 固有の report として扱い、ほかの profiler が同じ形式を持つ必要はありません。

```bash
# qws は Fugaku 系 build / run の内部で fapp + single を利用
bash programs/qws/build.sh Fugaku
bash programs/qws/run.sh Fugaku 1 4 12
```

追加オプションが必要なら、以下を併用できます。

- `BK_PROFILER_LEVEL`
  - `single|simple|standard|detailed` を上書き
- `BK_PROFILER_REPORT_FORMAT`
  - `text|csv|both` を上書き
- `BK_PROFILER_ARGS`
  - `fapp -C` にそのまま渡す追加引数
- `BK_PROFILER_REPORT_ARGS`
  - `fapp -A` / `fapppx -A` にそのまま渡す追加引数
- `BK_PROFILER_DIR`
  - raw profile data の出力先ディレクトリ名（既定値: `pa`）

archive の中身は概ね次の形になります。

```text
bk_profiler_artifact/
  meta.json
  raw/
    rep1/
    rep2/
  reports/
    fapp_A_rep1.txt
    cpu_pa_rep1.csv
```

より一般的な profiler helper の設計方針は [Profiler Support Guide](profiler-support.md) を参照してください。
level の早見表と portal 上の見え方は [Profiler Level Reference](profiler-level-reference.md) にまとめています。

### GPU アプリで `ncu` を使う場合

NVIDIA GPU 向けアプリでは、Nsight Compute CLI (`ncu`) を `bk_profiler` 経由で使えます。
MPI launcher 経由のアプリでは、`bk_profiler ncu` が既定で `--target-processes all` を付け、child process の CUDA kernel も採取対象にします。
MiyabiG と RC_GH200 のように計算ノード構成が同じ Grace-Hopper GPU 系の場合は、ジョブ投入方式だけを system 設定に任せ、アプリ側の build/run と profiler 採取は共通化するのが自然です。

```bash
BK_PROFILER_ARGS="--set full --kernel-name regex:your_kernel" \
bk_profiler ncu --level single --archive ../results/padata0.tgz --raw-dir ncu -- \
    mpirun -np 1 ./your_gpu_app input.inp
```

`ncu` の既定 level は `single` です。最初は採取時間を抑えるため、`single` または `simple` から始めてください。
raw report は `padata*.tgz` 内の `raw/rep1/` に保存され、可能な場合は `reports/ncu_import_rep1.txt` に text report が保存されます。
site の既定 module に `ncu` が含まれない場合は、アプリ側で module を load するか、system 固有の module 変数を用意してください。
Genesis GH200 参照実装では `GENESIS_MIYABIG_MODULE` / `GENESIS_GH200_MODULE` で module を上書きできます。
既定の `ncu` が PATH にない場合は warning を出して profiler なしで benchmark 本体を実行しますが、`GENESIS_MIYABIG_PROFILER_TOOL=ncu`、`GENESIS_GH200_PROFILER_TOOL=ncu`、または `GENESIS_PROFILER_TOOL=ncu` を明示した場合は採取不能として失敗します。
profiler なしを明示する場合は `GENESIS_MIYABIG_PROFILER_TOOL=none`、`GENESIS_GH200_PROFILER_TOOL=none`、または `GENESIS_PROFILER_TOOL=none` を使えます。
level は `GENESIS_MIYABIG_PROFILER_LEVEL` / `GENESIS_GH200_PROFILER_LEVEL`、または共通の `GENESIS_PROFILER_LEVEL` で上書きできます。

---

## 6. ローカルテスト

### ログインノードでのテスト
```bash
# ビルドテスト
bash programs/<code>/build.sh FugakuLN
ls artifacts/

# 実行テスト
bash programs/<code>/run.sh FugakuLN 1
cat results/result  # FOM:値が含まれることを確認
ls results/         # 必要に応じてpadata*.tgzも確認
```

### 結果の確認ポイント
- `artifacts/` に実行ファイルが生成される
- `results/result` に `FOM:` を含む行が出力される
- エラーなく完了する

---

## 7. バッチジョブテスト

### test_submit.sh の使用方法
```bash
# list.csvの内容確認
cat programs/<code>/list.csv

# 1行目の設定でテスト実行
bash scripts/test_submit.sh <code> 1
```

### test_submit.sh の機能
- **引数検証**: プログラム名と行番号の妥当性チェック
- **設定表示**: 選択された実行条件の詳細表示
- **自動投入**: システムに応じたバッチジョブ投入

### 実行例
```bash
$ bash scripts/test_submit.sh qws 1
Selected configuration from programs/qws/list.csv (line 1):
  Fugaku,yes,1,4,12,0:10:00

Parsed values:
  system=Fugaku, enable=yes, mode=cross (from system.csv), queue_group=small (from system.csv)
  nodes=1, numproc_node=4, nthreads=12, elapse=0:10:00

pjsub -L rscunit=rscunit_ft01,rscgrp=small,node=1,elapse=0:10:00 ...
```

### エラー対処
```bash
# 行番号が範囲外の場合
$ bash scripts/test_submit.sh qws 10
Error: Line 10 does not exist in programs/qws/list.csv
Available lines: 1 to 2

Contents of programs/qws/list.csv:
Line# | Configuration
------|-------------
  H   | system,enable,nodes,numproc_node,nthreads,elapse
    1 | Fugaku,yes,1,4,12,0:10:00
    2 | FugakuLN,yes,1,1,1,0:10:00
```

### 対応システム
- **Fugaku/FugakuCN**: PJM（富岳）
- **MiyabiG/MiyabiC**: PBS（Miyabi）
- **RC_GH200/RC_DGXSP/RC_GENOA/RC_FX700**: SLURM（クラウド）
- **FugakuLN**: テスト専用（投入なし）

**注意**: トークンを消費するプロジェクトでは、`groups`の第二要素が自動で選択されます。変更したい場合は`scripts/test_submit.sh`を編集してください。

---

## 8. PR作成

### コミット・プッシュ
```bash
# 変更をステージング
git add programs/<code>/

# コミット（[code:<code>]で追加したアプリのみテスト実行）
git commit -m "Add new app <code>

[code:<code>]

- Implement build.sh for multiple systems
- Add run.sh with proper FOM output
- Configure list.csv for target systems
- Test completed on FugakuLN"

# プッシュ
git push origin add-<code>
```

**注意**: `[code:<code>]`をコミットメッセージに含めることで、CI/CDパイプラインでは追加したアプリのみがテスト実行され、既存の全プログラムのテストは実行されません。これにより実行時間を大幅に短縮できます。

### PR作成時の記載内容
**タイトル:** `Add new application: <code>`

**説明:**
```markdown
## 新しいアプリケーション: <code>

### 概要
- アプリケーション名: <code>
- ソースコード: https://github.com/your-org/your-app
- 性能指標: [FOMの説明]

### テスト済み環境
- [x] FugakuLN (ログインノード)
- [x] Fugaku (バッチジョブ)
- [ ] MiyabiG
- [ ] MiyabiC

### 確認事項
- [x] build.sh が正常に動作
- [x] run.sh が FOM を出力
- [x] test_submit.sh でバッチジョブ投入成功
- [x] 結果フォーマットが正しい
```

### レビューポイント
- システム別ビルド設定の妥当性
- 結果フォーマットの正確性
- エラーハンドリングの適切性
- ドキュメントの更新

---

## 注意事項

### CI/CD環境
- 各パイプラインは独立したディレクトリで実行
- `artifacts/` と `results/` は自動的に管理される
- ビルド・実行ファイルの衝突は基本的に発生しない

### Git リポジトリの取り扱い
- `build.sh` と `run.sh` 両方でcloneする場合、ディレクトリ衝突に注意
- 既存チェック: `[[ -d repo ]] || git clone ...`
