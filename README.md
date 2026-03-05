# BenchKit: 継続ベンチマーク実行基盤

BenchKit は、複数のアプリケーションを多拠点環境で継続的にベンチマーク実行し、その結果を収集・公開するための CI パイプラインフレームワークです。

**📋 新しいアプリケーションの追加方法**: [ADD_APP.md](ADD_APP.md) を参照してください。

---

## 目的

- 複数のコード（10〜50程度）を複数の拠点・システム（10〜30程度）で継続ベンチマーク実行
- ビルドと実行の分離・統合に対応（クロスコンパイルやJacamar-CI利用）
- サイト依存の環境条件への対応
- ベンチマーク結果の保存・可視化・性能推定
- **BenchParkフレームワークとの統合**（Spack/Rambleベースのベンチマーク管理）

---

## プロジェクト構成
```
benchkit/
├── programs/
│   └── <code名>/
│       ├── build.sh      # システム別ビルドスクリプト
│       ├── run.sh        # システム別実行スクリプト
│       └── list.csv      # ベンチマーク実行条件定義
├── config/
│   └── benchpark-monitor/
│       └── list.csv      # BenchPark監視対象定義
├── result_server/
│   ├── routes/
│   │   ├── receive.py    # ベンチマーク結果(JSON)受信
│   │   ├── results.py    # ベンチマーク結果表示
│   │   └── upload_tgz.py # 詳細データ(TGZ)受信・UUID連携
│   ├── templates/        # Webテンプレート
│   ├── utils/           # システム情報管理
│   └── app.py           # Webサーバメイン
├── scripts/
│   ├── matrix_generate.sh # CI YAML生成スクリプト
│   ├── job_functions.sh   # 共通関数定義
│   ├── result.sh         # 結果JSON変換
│   ├── send_results.sh   # 結果転送
│   ├── wait_for_nfs.sh   # NFS同期待機
│   ├── test_submit.sh    # テスト実行用
│   ├── benchpark_matrix_generate.sh # BenchPark用CI生成
│   ├── benchpark_functions.sh       # BenchPark共通関数
│   ├── benchpark_runner.sh          # BenchPark実行管理
│   └── convert_benchpark_results.py # BenchPark結果変換
├── .gitlab-ci.yml        # メインCI定義
├── benchpark/            # BenchParkフレームワーク（サブモジュール）
├── system.csv           # 実行システム定義
├── queue.csv            # キューシステム定義
└── README.md
```

## CI パイプラインの構成

### 1. メインパイプライン
- `programs/<code>/list.csv`, `system.csv`, `queue.csv` を読み込み
- `scripts/matrix_generate.sh` により `.gitlab-ci.generated.yml` を自動生成
- クロスコンパイル・ネイティブコンパイルの2モードに対応

### 2. ベンチマーク実行パイプライン

| モード | 実行内容 |
|--------|----------|
| `cross` | ビルド→実行の2段階（ビルドはアーティファクト化） |
| `native` | 1ジョブでビルド＋実行を同時実行 |

- `build.sh`、`run.sh` にはシステム名を渡し、システム別の環境設定が可能
- `scripts/result.sh` で結果をJSON形式に変換
- `scripts/send_results.sh` で結果サーバに転送・性能推定トリガー

### 3. 結果転送・保存
- `results/result[0-9].json` を結果サーバに転送
- サーバが識別子（`id`）と受信時間（`timestamp`）を返却
- `results/padata[0-9].tgz` があれば詳細データも転送
- 必要に応じて性能推定をトリガー


## 設定ファイル

### `system.csv` - システム・ランナー定義
```csv
system,tag,roles,queue
Fugaku,fugaku_login1,build,none
Fugaku,fugaku_jacamar,run,FJ
MiyabiG,miyabi_g_login,build,none
MiyabiG,miyabi_g_jacamar,run,PBS_Miyabi
MiyabiC,miyabi_c_login,build,none
MiyabiC,miyabi_c_jacamar,run,PBS_Miyabi
```

### `queue.csv` - キューシステム定義
```csv
queue,submit_cmd,template
FJ,pjsub,"-L rscunit=rscunit_ft01,rscgrp=${queue_group},elapse=${elapse},node=${nodes} --mpi max-proc-per-node=${numproc_node} -x PJM_LLIO_GFSCACHE=/vol0004"
PBS_Miyabi,qsub,"-q ${queue_group} -l select=${nodes} -l walltime=${elapse} -W group_list=gq49"
SLURM_RC_GH200,sbatch,"-p qc-gh200 -t ${elapse} -N ${nodes} --ntasks-per-node=${numproc_node} --cpus-per-task=${nthreads}"
none,none,none
```

### `programs/<code>/list.csv` - ベンチマーク実行条件
同一システムで異なるノード数・プロセス数の組み合わせを複数定義可能：

```csv
system,mode,queue_group,nodes,numproc_node,nthreads,elapse
# 同一システム（Fugaku）で異なる実行条件
Fugaku,cross,small,1,4,12,0:10:00
Fugaku,cross,small,2,4,12,0:20:00
Fugaku,cross,small,4,4,12,0:30:00
# MiyabiG/MiyabiCでの実行例
MiyabiG,cross,debug-g,1,1,72,0:10:00
MiyabiC,cross,debug-c,1,1,112,0:10:00
```


## CI実行制御

### GitHub → GitLab 同期
- GitHub での開発 → GitHub Actions で GitLab に自動同期
- GitLab への同期 → GitLab CI でベンチマーク実行

### 自動スキップ機能
重いベンチマーク処理を避けるため、以下のファイルのみ変更時は自動スキップ：
- `README.md`, `ADD_APP.md` （ドキュメント）
- `result_server/templates/*.html` （Webテンプレート）
- `.kiro/**/*`, `.vscode/**/*` （設定ファイル）

### 実行制御オプション

**コミットメッセージによる制御：**
```bash
# 特定システムのみ実行
git commit -m "Fix bug [system:MiyabiG,MiyabiC]"

# 特定プログラムのみ実行  
git commit -m "Update qws [code:qws,genesis]"

# 組み合わせ可能
git commit -m "Test changes [system:MiyabiG] [code:qws]"
```

**APIトリガー制御：**
```bash
curl -X POST --fail \
  -F token=$TOKEN \
  -F ref=main \
  -F "variables[system]=MiyabiG,MiyabiC" \
  -F "variables[code]=qws" \
  https://gitlab.example.com/api/v4/projects/PROJECT_ID/trigger/pipeline
```

**BenchPark統合実行：**
```bash
# BenchPark用CI設定生成
bash scripts/benchpark_matrix_generate.sh

# 特定システムでBenchPark実行
bash scripts/benchpark_matrix_generate.sh system=fugaku app=qws
```

---

## システム別実行環境
`build.sh`と`run.sh`はシステム名を引数として受け取り、システム別の環境設定（モジュール、MPI設定等）に対応可能。

## 動作要件
- POSIX環境（`bash`, `awk`, `cut`等の標準コマンド）
- `yq`, `jq`等のシステム依存ツールは使用しない設計
