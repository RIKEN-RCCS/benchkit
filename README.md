# BenchKit: 継続ベンチマーク実行基盤

BenchKit は、複数のアプリケーションを多拠点環境で継続的にベンチマーク実行し、その結果を収集・公開するための CI パイプラインフレームワークです。
FugakuNEXTプロジェクトのBenchmarkフレームワークのプロトタイプも兼ねています。このリポジトリは将来的に統合されたり削除される可能性があります。
必要であればFugakuNEXT向け性能推定用リポジトリのCI/CDもトリガします。

---

## 目的

- 複数のコード（10〜50程度）
- 複数の拠点の複数システム（10〜30程度）
- ビルドと実行の分離・統合に対応（クロスコンパイルやJacamar-ciの利用）
- サイト依存の環境条件への対応
- ベンチマーク結果の保存・可視化
- ベンチマーク結果を用いた性能推定

---

## プロジェクト構成
```
benchkit/
├── programs/
│ └── <code名>/
│   ├── build.sh # システムに合わせたビルドを実行
│   ├── run.sh # システムに合わせたジョブの実行
│   └── list.csv # システムに合わせたベンチマーク定義
├── result_server/
│ ├── route/
│ │ ├── receive.py # ベンチマーク結果(json)受け取り
│ │ ├── result.py # ベンチマーク結果表示
│ │ └── upload_tgz.py # ベンチマーク結果(詳細PAデータ等tgz)受け取り、uuidでjsonと連携
│ ├── templates/
│ │ ├── hard_env.html # ハードスペック
│ │ └── results.html # 結果表
│ └── app.py # サーバ用mainプログラム
├── scripts/
│ ├── matrix_generate.sh # ベンチマーク用の子パイプラインを生成（名称変更するかもしれない
│ ├── job_functions.sh # matrix_generate.sh内の関数の定義用スクリプト
│ ├── result.sh # 結果をjsonに変換するスクリプト
│ ├── ~~run_benchmark.sh # 各ジョブのドライバスクリプト（＜－結果的に使わなくてよいかもしれない~~
│ └── send_results.sh # 結果転送
├── .gitignore # 管理除外ファイルの定義
├── .gitlab-ci.yml # 親パイプライン定義
├── README.md
├── system.csv # 実行システム（ランナー）定義
└── queue.csv # queueシステム定義
```


---

## CI パイプラインの構成

### 1. 一次パイプライン

- `program/<code>/list.csv`, `system.csv`, `queue.csv` を読み込み
- `scripts/matrix_generate.sh` により `.gitlab-ci.generated.yml` を自動生成
- クロスコンパイル・ネイティブコンパイルおよび実行に対応（2モード）

### 2 二次パイプライン（ベンチマーク実行）

| Build & run Mode　 | 実行内容                          |
|-------------------|-----------------------------------|
| `native`          | 1パイプライン（1ジョブ）でビルド＋実行  |
| `cross`           | 1つめのパイプラインでビルドを実行（アーティファクト化）、2つめのパイプラインで実行 |

- `build.sh`、`run.sh` には `system`（system名）を渡し、systemごとの条件を切り替え可能（以下で詳しく）
- `scripts/result.sh` で結果post用JSON作成など


### 2.a 二次パイプライン最終ステージ
`send_results.sh`にて各ジョブごとに出力されたベンチ結果を送信＆必要に応じて性能推定をトリガ

- `results/result[0-9].json`を結果サーバに転送（`curl -X POST`)
- サーバが受け取り識別子（`id`）と受け取り時間(`timestamp`)を返却するので、`id`と`timestamp`を抽出する
- results/padata[0-9].tgzがあれば、`id`と`timestamp`を添えて`POST`
- 必要に応じて性能推定をトリガ(性能推定用データを識別するため`id`を添えて`POST`)


### `system.csv` (set by CB manager, skipable with #)
```csv
system,tag,roles
#Fugaku,fugaku_login1,build,FJ
#Fugaku,fugaku_jacamar,run,FJ
FugakuLN,fugaku_login1,build_run,none
#FugakuCN,fugaku_jacamar,build_run,FJ
```

### `queue.csv` (set by CB manager, skipable with #)
```csv
queue,submit_cmd,template
FJ,pjsub,"-L rscunit=rscunit_ft01,rscgrp=${queue_group},elapse=${elapse},node=${nodes} -x PJM_LLIO_GFSCACHE=/vol0004"
none,none,none
```

### `program/<code>/list.csv` (set by program developer, skipable with #)

```csv
system,mode,queue_group,nodes,numproc_node,nthreads,elapse
Fugaku,cross,small,1,1,6,0:10:00
FugakuLN,native,small,1,1,6,0:10:00
FugakuCN,native,small,1,1,6,0:10:00
```


---

##  Systemごとの実行条件分岐
`build.sh`と`run.sh` は `system` を引数に受け取り、実行環境（モジュール、MPI設定など）を`sytem`に応じて切り替えることが可能。

~~必要に応じて `config/runparams.csv` のような補助ファイルを導入し、実行パラメータを集中管理することも可能?。~~
(program/<code>/list.csvですべて定義できるか検討)


## 結果の受け取りと表示


## 動作要件
POSIX 環境で動作（`bash`, `awk`, `cut` 等の標準コマンド）するように。
スクリプトでは、`yq`、`jq` 等、systemによってインストールされていない可能性があるツールは使用しない。

## 今後の拡張想定

- プログラム数：dummyでもよいので50程度まで拡張
- 実行拠点数：dummyでもよいので30程度まで拡張
