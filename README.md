# BenchKit: 継続ベンチマーク実行基盤

BenchKit は、複数のアプリケーションを多拠点環境で継続的にベンチマーク実行し、その結果を収集・公開するための CI パイプラインフレームワークです。

**📋 新しいアプリケーションの追加方法**: [ADD_APP.md](ADD_APP.md) を参照してください。
**🏢 新しい拠点の追加方法**: [ADD_SITE.md](ADD_SITE.md) を参照してください。
**📊 性能推定支援機能**: [ESTIMATE.md](ESTIMATE.md) を参照してください。

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
│   │   ├── results.py        # 結果一覧・詳細・比較・使用量レポートページ
│   │   ├── estimated.py      # 推定結果ページ
│   │   ├── auth.py           # TOTP認証（ログイン/セットアップ/ログアウト）
│   │   └── admin.py          # ユーザー管理（CRUD/招待リンク）
│   ├── templates/
│   │   ├── results.html              # 結果一覧（公開）
│   │   ├── results_confidential.html # 結果一覧（認証付き、機密データ含む）
│   │   ├── result_detail.html        # 個別結果詳細（Chart.jsグラフ）
│   │   ├── result_compare.html       # リグレッション比較
│   │   ├── estimated_results.html    # 推定結果一覧
│   │   ├── systemlist.html           # システム情報一覧
│   │   ├── auth_login.html           # ログインページ（Email + TOTP）
│   │   ├── auth_setup.html           # TOTP初期登録（QRコード表示）
│   │   ├── admin_users.html          # ユーザー管理画面
│   │   ├── usage_report.html         # ノード時間使用量レポート（admin専用）
│   │   ├── _navigation.html          # 共通ナビゲーション（タブ型、認証時タブ拡張）
│   │   ├── _pagination.html          # ページネーションUI部品
│   │   ├── _results_table.html       # 結果テーブル部品（フィルタ・比較UI内蔵）
│   │   ├── _filter_dropdowns.html    # フィルタドロップダウン部品（推定結果用）
│   │   └── _table_base.html          # テーブル基盤テンプレート（ツールチップ定義）
│   ├── utils/
│   │   ├── results_loader.py     # 結果ファイル読み込み・集約・ページネーション
│   │   ├── node_hours.py        # ノード時間計算・会計年度判定・クロス集計
│   │   ├── result_file.py        # ファイルアクセス・権限管理
│   │   ├── system_info.py        # システム情報管理
│   │   ├── totp_manager.py       # TOTP認証（秘密鍵生成/QR/検証/レート制限）
│   │   └── user_store.py         # Redisベースユーザーストア（CRUD/招待トークン）
│   ├── tests/                    # テストスイート（102テスト）
│   ├── app.py                    # 本番用アプリ（main + dev）
│   ├── app_dev.py                # ローカル開発用（Redis/TOTP不要、スタブモジュール内蔵）
│   └── create_admin.py           # 初期adminユーザー作成CLIツール
├── scripts/
│   ├── matrix_generate.sh    # CI YAML生成スクリプト
│   ├── job_functions.sh      # 共通関数定義（CSVパース、System_CSV検索）
│   ├── bk_functions.sh       # FOM/SECTION/OVERLAP出力標準化関数
│   ├── result.sh             # 結果JSON変換（SECTION/OVERLAP対応、pipeline_timing付加）
│   ├── send_results.sh       # 結果転送（uuid/timestamp書き戻し）
│   ├── record_timestamp.sh   # Unixエポックタイムスタンプ記録
│   ├── collect_timing.sh     # パイプラインタイミング収集（build/queue/run時間）
│   ├── estimate_common.sh    # 性能推定共通ライブラリ
│   ├── run_estimate.sh       # 推定実行ラッパー
│   ├── send_estimate.sh      # 推定結果転送
│   ├── fetch_result_by_uuid.sh # UUID指定結果取得
│   ├── generate_estimate_from_uuid.sh # UUID指定推定パイプライン生成
│   ├── wait_for_nfs.sh       # NFS同期待機（現在コメントアウト中）
│   └── test_submit.sh        # テスト実行用
├── .gitlab-ci.yml            # メインCI定義
├── config/
│   ├── system.csv            # 実行システム定義
│   ├── queue.csv             # キューシステム定義
│   └── system_info.csv       # システムハードウェア情報
├── ADD_APP.md                # アプリ追加手順（開発者向け）
├── ADD_SITE.md               # 拠点追加手順（拠点管理者向け）
├── ESTIMATE.md               # 性能推定機能（推定開発者向け）
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
| `/results/` | 結果一覧（公開、ページネーション・フィルタ対応） |
| `/results/confidential` | 結果一覧（TOTP認証付き、機密データ含む、ページネーション・フィルタ対応） |
| `/results/detail/<filename>` | 個別結果詳細（Chart.jsグラフ、データテーブル、ビルド情報） |
| `/results/compare?files=a,b` | リグレッション比較（複数結果の差分表示） |
| `/results/usage` | ノード時間使用量レポート（admin専用、月次/半期/年度切替、会計年度選択、期間フィルタ） |
| `/estimated/` | 推定結果一覧（ページネーション・フィルタ対応、認証時は機密データ含む） |

結果一覧・推定結果ページのクエリパラメータ:
- `page` - ページ番号（1始まり、範囲外は自動リダイレクト）
- `per_page` - 表示件数（50/100/200、デフォルト100）
- `system` - SYSTEMフィルタ
- `code` - CODEフィルタ
- `exp` - Expフィルタ
| `/systemlist` | システム情報一覧 |
| `/auth/login` | TOTP認証ログイン |
| `/auth/setup/<token>` | TOTP初期登録（招待リンク経由） |
| `/auth/logout` | ログアウト |
| `/admin/users` | ユーザー管理（admin専用） |

### 結果表示機能

- サーバーサイドページネーション: 表示件数選択（50/100/200件）、First/Previous/Next/Last ナビゲーション
- サーバーサイドフィルタ: SYSTEM/CODE/Exp ドロップダウンによる絞り込み（フィルタはテーブルヘッダ行に内蔵、Exp は CODE に連動、フィルタ条件はページ遷移時に保持）
- 結果テーブル列: Timestamp, SYSTEM, CODE, FOM, Compare, FOM version, Exp, Nodes, Proc/node, Thread/proc, JSON, PA Data, Mode, Trigger, Pipeline, Detail
- ナビゲーション: ブラウザタブ風のアクティブ表示、認証時はタブが拡張（Public/All Results/Estimated）
- スカラー型メトリクス: テーブル形式で表示
- ベクトル型メトリクス: Chart.js によるインタラクティブグラフ（メッセージサイズ vs バンド幅/レイテンシ等）
- リグレッション比較: 複数結果を選択して差分をグラフ・テーブルで比較
- Spackビルド情報: コンパイラ、MPI、パッケージリストの表示

### 認証システム（TOTP）

結果サーバはTOTP（Time-based One-Time Password）ベースの認証を採用しています。

- 管理者が招待リンクを発行 → ユーザーがTOTPアプリ（Google Authenticator等）で登録
- ログイン: メールアドレス + 6桁TOTPコード
- セキュリティ: リプレイ攻撃防止（90秒窓）、ブルートフォース保護（5回失敗で5分ロック）
- ユーザー情報・セッションはRedisに保存
- issuer名は環境変数 `TOTP_ISSUER` で設定（デフォルト: "BenchKit"）
  - 本番: `TOTP_ISSUER=BenchKit`、開発: `TOTP_ISSUER=BenchKit-Dev`
  - ローカル開発（app_dev.py）では自動的に `-Local` サフィックスが付加

初期adminユーザーの作成:
```bash
cd result_server
python create_admin.py --email admin@example.com --name "Admin" --affiliations admin
# → 招待リンクが表示される → ブラウザで開いてTOTP登録
```

### ローカル開発

Redis/TOTP/APIキー不要で結果表示を確認できます:

```bash
cd result_server
pip install flask flask-session pyotp "qrcode[pil]"
python app_dev.py --generate-sample
# → http://localhost:8800/results
```

### テスト

```bash
cd result_server
pip install pytest hypothesis fakeredis
python -m pytest tests/ -v
```

---

## CI パイプラインの構成

### 1. メインパイプライン
- `programs/<code>/list.csv`, `config/system.csv`, `config/queue.csv` を読み込み
- `scripts/matrix_generate.sh` により `.gitlab-ci.generated.yml` を自動生成
- クロスコンパイル・ネイティブコンパイルの2モードに対応
- `list.csv` の `enable` カラムでジョブの有効/無効を制御
- `mode`/`queue_group` は `config/system.csv` で一元管理

### 2. ベンチマーク実行パイプライン

| モード | パイプラインフロー |
|--------|----------|
| `cross` | build → run → send_results [`collect_timing.sh`, `result.sh`, `send_results.sh`] |
| `native` | build_run → send_results [`collect_timing.sh`, `result.sh`, `send_results.sh`] |

- `build.sh`、`run.sh` にはシステム名を渡し、システム別の環境設定が可能
- `run.sh` は `$1`=system, `$2`=nodes, `$3`=numproc_node, `$4`=nthreads の4引数を受け取る
- `run.sh` は `scripts/bk_functions.sh` を `source` し、`bk_emit_result` / `bk_emit_section` / `bk_emit_overlap` で標準化された結果出力を行う
- `record_timestamp.sh` は run/build_run ジョブ（計算ノード上）でビルド・実行の開始/終了時刻を記録する
- `collect_timing.sh` と `result.sh` は send_results ジョブ（Docker ランナー `fncx-curl-jq` 上）で実行される。`collect_timing.sh` で `pipeline_timing`（build/queue/run時間）を集計し、`result.sh` で結果をJSON形式に変換（`pipeline_timing` 情報を自動付加）する
- `scripts/send_results.sh` で結果サーバに転送・性能推定トリガー

### 3. 結果転送・保存
- `results/result[0-9].json` を結果サーバに転送
- サーバが識別子（`id`）と受信時間（`timestamp`）を返却し、Result_JSON に書き戻し
- `results/padata[0-9].tgz` があれば詳細データも転送
- 推定対象システム（MiyabiG等）の場合、性能推定パイプラインをトリガー

### 4. 性能推定パイプライン
ベンチマーク結果から他システムでの性能を推定します。詳細は [ESTIMATE.md](ESTIMATE.md) を参照。

- 推定対象システム: `ESTIMATE_SYSTEMS`（job_functions.sh で定義、例: MiyabiG, RC_GH200）
- `estimate.sh` がアプリ固有の推定ロジックを実装（`programs/<code>/estimate.sh`）
- `estimate_common.sh` が共通関数（API呼び出し、JSON出力等）を提供
- UUID指定による再推定もサポート（`estimate_uuid` 変数でトリガー）

### 5. BenchPark統合パイプライン
- `benchpark-bridge/config/apps.csv` で監視対象を定義
- `benchpark-bridge/scripts/ci_generator.sh` により `.gitlab-ci.benchpark.yml` を自動生成
- `benchpark-bridge/scripts/runner.sh` でBenchPark（Spack/Ramble）を実行
- `benchpark-bridge/scripts/result_converter.py` でRamble結果をBenchKit JSON形式に変換
- 結果は `scripts/send_results.sh` で結果サーバに転送

---

## 設定ファイル

### `config/system.csv` - システム・ランナー定義
```csv
system,mode,tag_build,tag_run,queue,queue_group
Fugaku,cross,fugaku_login1,fugaku_jacamar,FJ,small
FugakuLN,native,,fugaku_login1,none,small
MiyabiG,cross,miyabi_g_login,miyabi_g_jacamar,PBS_Miyabi,debug-g
MiyabiC,cross,miyabi_c_login,miyabi_c_jacamar,PBS_Miyabi,debug-c
```

### `config/queue.csv` - キューシステム定義
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
system,enable,nodes,numproc_node,nthreads,elapse
# 同一システム（Fugaku）で異なる実行条件
Fugaku,yes,1,4,12,0:10:00
Fugaku,yes,2,4,12,0:20:00
Fugaku,yes,4,4,12,0:30:00
# 無効化された設定（enable=noでスキップ）
FugakuCN,no,1,4,12,0:10:00
# MiyabiG/MiyabiCでの実行例
MiyabiG,yes,1,1,72,0:10:00
MiyabiC,no,1,1,112,0:10:00
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

| タグ | BenchKit | BenchPark | 用途 |
|------|----------|-----------|------|
| (タグなし) | ✅ 実行 | ❌ スキップ | 通常のベンチマーク実行 |
| `[park-only]` | ❌ スキップ | ✅ フル実行 | BenchPark開発・テスト |
| `[park-send]` | ❌ スキップ | ✅ 送信のみ | BenchPark結果再送信 |
| `[benchpark]` | ✅ 実行 | ✅ 実行 | BenchPark設定変更時 |
| `[skip-ci]` | ❌ スキップ | ❌ スキップ | ドキュメント更新等 |

```bash
# 特定システムのみ実行
git commit -m "Fix bug [system:MiyabiG,MiyabiC]"

# 特定プログラムのみ実行
git commit -m "Update qws [code:qws,genesis]"

# 組み合わせ可能
git commit -m "Test changes [system:MiyabiG] [code:qws]"

# BenchParkのみ実行（setup/run/convert/send）
git commit -m "Fix BenchPark runner [park-only]"

# BenchPark結果送信のみ（convert/send）
git commit -m "Fix result converter [park-send]"

# CI完全スキップ（ドキュメント更新等）
git commit -m "Update docs [skip-ci]"
```

**APIトリガー制御：**

| 変数 | 説明 | 例 |
|------|------|-----|
| `system` | システムフィルタ（BenchKit/BenchPark共通） | `MiyabiG,MiyabiC` |
| `code` | BenchKitプログラムフィルタ | `qws,genesis` |
| `app` | BenchParkアプリフィルタ | `osu-micro-benchmarks` |
| `benchpark` | BenchParkパイプライン有効化 | `true` |
| `park_only` | BenchParkのみ実行（BenchKitスキップ） | `true` |
| `park_send` | BenchPark送信のみ（BenchKitスキップ） | `true` |

分岐パターン:

| 変数指定 | BenchKit | BenchPark | 説明 |
|----------|----------|-----------|------|
| `code=scale-letkf` | ✅ scale-letkfのみ | ❌ スキップ | BenchKit特定コード実行 |
| `park_only=true` | ❌ スキップ | ✅ 全アプリ | BenchParkフル実行 |
| `park_only=true app=osu-micro-benchmarks` | ❌ スキップ | ✅ OSUのみ | BenchPark特定アプリ実行 |
| `park_send=true` | ❌ スキップ | ✅ 全アプリ送信のみ | BenchPark結果再送信 |
| `park_send=true app=osu-micro-benchmarks` | ❌ スキップ | ✅ OSU送信のみ | BenchPark特定アプリ送信 |
| `benchpark=true` | ✅ 全実行 | ✅ 全アプリ | 両方実行 |
| `benchpark=true code=qws app=osu-micro-benchmarks` | ✅ qwsのみ | ✅ OSUのみ | 両方フィルタ付き |
| (変数なし) | ✅ 全実行 | ❌ スキップ | 通常のCI |

> **Note**: `code` のみ指定時にBenchParkが動かないのは、`code` がBenchKit専用のフィルタであるため。BenchParkを動かすには `benchpark=true`、`park_only=true`、`park_send=true` のいずれかを明示的に指定する必要がある。この制御ロジックは将来的に整理予定。

```bash
# BenchKit: 特定コードのみ
curl -X POST --fail \
  -F token=$TOKEN -F ref=main \
  -F "variables[code]=qws" \
  https://gitlab.example.com/api/v4/projects/PROJECT_ID/trigger/pipeline

# BenchPark: OSUのsend-onlyのみ
curl -X POST --fail \
  -F token=$TOKEN -F ref=main \
  -F "variables[park_send]=true" \
  -F "variables[app]=osu-micro-benchmarks" \
  https://gitlab.example.com/api/v4/projects/PROJECT_ID/trigger/pipeline

# BenchPark: 全アプリフル実行
curl -X POST --fail \
  -F token=$TOKEN -F ref=main \
  -F "variables[park_only]=true" \
  https://gitlab.example.com/api/v4/projects/PROJECT_ID/trigger/pipeline
```

---

## システム別実行環境
`build.sh`と`run.sh`はシステム名を引数として受け取り、システム別の環境設定（モジュール、MPI設定等）に対応可能。

## 動作要件
- POSIX環境（`bash`, `awk`, `cut`等の標準コマンド）
- `yq`, `jq`等のシステム依存ツールは使用しない設計
- 結果サーバ: Python 3, Flask, Gunicorn, Redis（本番）, pyotp, qrcode[pil]
- テスト: pytest, hypothesis, fakeredis
