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
│       ├── build.sh          # システム別ビルドスクリプト
│       ├── run.sh            # システム別実行スクリプト
│       └── list.csv          # ベンチマーク実行条件定義
├── benchpark-bridge/
│   ├── config/
│   │   └── apps.csv          # BenchPark監視対象定義
│   └── scripts/
│       ├── common.sh         # BenchPark共通関数
│       ├── ci_generator.sh   # BenchPark用CI YAML生成
│       ├── runner.sh         # BenchPark実行管理
│       └── result_converter.py # BenchPark結果変換（Ramble→BenchKit形式）
├── result_server/
│   ├── routes/
│   │   ├── api.py            # 統合データ受信API（結果/推定/PA Data）
│   │   ├── results.py        # 結果一覧・詳細・比較ページ
│   │   └── estimated.py      # 推定結果ページ
│   ├── templates/
│   │   ├── results.html              # 結果一覧（公開）
│   │   ├── results_confidential.html # 結果一覧（OTP認証付き）
│   │   ├── result_detail.html        # 個別結果詳細（Chart.jsグラフ）
│   │   ├── result_compare.html       # リグレッション比較
│   │   ├── estimated_results.html    # 推定結果一覧
│   │   ├── systemlist.html           # システム情報一覧
│   │   ├── _navigation.html          # 共通ナビゲーション
│   │   ├── _results_table.html       # 結果テーブル部品
│   │   ├── _table_base.html          # テーブル基盤テンプレート
│   │   └── _otp_modal.html           # OTP認証モーダル
│   ├── utils/
│   │   ├── results_loader.py     # 結果ファイル読み込み・集約
│   │   ├── result_file.py        # ファイルアクセス・権限管理
│   │   ├── system_info.py        # システム情報管理
│   │   ├── otp_redis_manager.py  # OTP認証（Redis）
│   │   └── otp_manager.py        # OTP認証（ファイルベース）
│   ├── tests/                    # テストスイート
│   ├── app.py                    # 本番用アプリ（main + dev）
│   └── app_dev.py                # ローカル開発用（Redis/OTP不要）
├── scripts/
│   ├── matrix_generate.sh    # CI YAML生成スクリプト
│   ├── job_functions.sh      # 共通関数定義
│   ├── result.sh             # 結果JSON変換
│   ├── send_results.sh       # 結果転送
│   ├── wait_for_nfs.sh       # NFS同期待機
│   ├── test_submit.sh        # テスト実行用
│   ├── run_benchmark.sh      # ベンチマーク実行
│   ├── check_results.sh      # 結果確認
│   └── debug_job.sh          # デバッグ用
├── .gitlab-ci.yml            # メインCI定義
├── system.csv                # 実行システム定義
├── queue.csv                 # キューシステム定義
└── README.md
```

---

## 結果サーバ

### 概要
Flask ベースの Web アプリケーションで、ベンチマーク結果の受信・保存・表示を行います。

### デプロイ構成
- nginx リバースプロキシ → Gunicorn
- 本番（port 8800）: `app.py:app`（prefix=""）
- 開発（port 8801）: `app.py:app_dev`（prefix="/dev"）

### API エンドポイント

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/ingest/result` | POST | 結果JSON受信 |
| `/api/ingest/estimate` | POST | 推定結果JSON受信 |
| `/api/ingest/padata` | POST | PA Data (tgz) 受信 |
| `/write-api` | POST | 互換ルート（deprecated → `/api/ingest/result`） |
| `/write-est` | POST | 互換ルート（deprecated → `/api/ingest/estimate`） |
| `/upload-tgz` | POST | 互換ルート（deprecated → `/api/ingest/padata`） |

### Web ページ

| パス | 説明 |
|---|---|
| `/results/` | 結果一覧（公開） |
| `/results/confidential` | 結果一覧（OTP認証付き、機密データ含む） |
| `/results/detail/<filename>` | 個別結果詳細（Chart.jsグラフ、データテーブル、ビルド情報） |
| `/results/compare?files=a,b` | リグレッション比較（複数結果の差分表示） |
| `/estimated/` | 推定結果一覧 |
| `/systemlist` | システム情報一覧 |

### 結果表示機能

- スカラー型メトリクス: テーブル形式で表示
- ベクトル型メトリクス: Chart.js によるインタラクティブグラフ（メッセージサイズ vs バンド幅/レイテンシ等）
- リグレッション比較: 複数結果を選択して差分をグラフ・テーブルで比較
- Spackビルド情報: コンパイラ、MPI、パッケージリストの表示

### ローカル開発

Redis/OTP/APIキー不要で結果表示を確認できます:

```bash
cd result_server
pip install flask flask-session
python app_dev.py --generate-sample
# → http://localhost:8800/results
```

### テスト

```bash
cd result_server
pip install pytest
python -m pytest tests/ -v
```

---

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

### 4. BenchPark統合パイプライン
- `benchpark-bridge/config/apps.csv` で監視対象を定義
- `benchpark-bridge/scripts/ci_generator.sh` により `.gitlab-ci.benchpark.yml` を自動生成
- `benchpark-bridge/scripts/runner.sh` でBenchPark（Spack/Ramble）を実行
- `benchpark-bridge/scripts/result_converter.py` でRamble結果をBenchKit JSON形式に変換
- 結果は `scripts/send_results.sh` で結果サーバに転送

---

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

# BenchParkのみ実行
git commit -m "Fix BenchPark runner [park-only]"

# BenchPark結果送信のみ
git commit -m "Fix result converter [park-send]"

# CI完全スキップ（ドキュメント更新等）
git commit -m "Update docs [skip-ci]"
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

---

## システム別実行環境
`build.sh`と`run.sh`はシステム名を引数として受け取り、システム別の環境設定（モジュール、MPI設定等）に対応可能。

## 動作要件
- POSIX環境（`bash`, `awk`, `cut`等の標準コマンド）
- `yq`, `jq`等のシステム依存ツールは使用しない設計
- 結果サーバ: Python 3, Flask, Gunicorn, Redis（本番）
