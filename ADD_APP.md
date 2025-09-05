# アプリ追加手順（開発者向け）

このドキュメントは、BenchKit に新しいアプリ（プログラム）を追加する手順を開発者向けにまとめたものです。
サンプルアプリ `qws` を参考に、新しいアプリ `<code>` を追加して PR を作成するまでを説明します。

## 目次

1. [リポジトリの Fork と Clone](#1-リポジトリの-fork-と-clone)
2. [作業用ブランチの作成](#2-作業用ブランチの作成)
3. [サンプルアプリのコピー](#3-サンプルアプリのコピー)
4. [build.sh の確認](#4-buildsh-の確認)
5. [run.sh の確認](#5-runsh-の確認)
6. [test\_submit.sh によるbatch jobを用いた確認](#6-test_submitsh-によるbatch-jobを用いた確認)
7. [変更のコミットと PR 作成](#7-変更のコミットと-pr-作成)
8. [注意事項](#8-注意事項)

---

## 1. リポジトリの Fork と Clone

まず、自分の GitHub アカウントに BenchKit を Fork します。

```bash
# Fork: https://github.com/RIKEN-RCCS/benchkit
git clone https://github.com/<yourname>/benchkit.git
cd benchkit
```

---

## 2. 作業用ブランチの作成

```bash
git checkout -b <code>
```

* `<code>` は追加するアプリの名前（例: `myapp`）に置き換えてください。

---

## 3. サンプルアプリのコピー

既存のサンプルアプリ `qws` をコピーして、新しいアプリ用に編集します。

```bash
cp -pr programs/qws/ programs/<code>
```

* コピーした `programs/<code>` 以下を編集してください：

  * `build.sh`  : 実行ファイルをコンパイルし、必要なファイルを `artifacts/` に保存するスクリプトです。
  * `run.sh`    : アプリケーションを実行し、結果を`results/`に保存するスクリプトです。
  * `list.csv`  : ジョブ投入用のパラメータを記載するファイルです。

---

## 4. build.sh の確認

```bash
# 富岳ログインノードでは、Xeon 向けビルド(FugakuLN)と、A64FX向けビルド(Fugaku)の確認ができます。
# FugakuCNは、計算ノード内でのビルド＆ランをするモードのため、ログインノードでのビルド確認はできません。
bash programs/<code>/build.sh FugakuLN

# artifacts 内のファイルを確認
ls artifacts/
```

* ビルドに必要な実行ファイルや補助ファイルが `artifacts/` に保存されていることを確認します。

---

## 5. run.sh の確認

```bash
# 富岳ログインノードでXeon環境でrun.shを試す場合はFugakuLNです。FugakuLNの場合、nodesは1にしてください。
bash programs/<code>/run.sh FugakuLN 1

# results 内に結果が生成されることを確認
ls results/

# ベンチマークの結果は、results/result に書きます。
# 各行が 1 つのベンチマークに対応しています。
# 各行は必ず性能指標（FOM:）のkeyを含む必要があります。
cat results/result
```

---

## 6. test\_submit.sh によるbatch jobを用いた確認

```bash
# 富岳ログインで、A64FX用実行ファイルを用いたrun.sh、FugakuCNとFugakuのテストをできます。
# 事前に"build.sh Fugaku"を用いてA64FX用実行ファイルを作成しておきます。
bash scripts/test_submit.sh <code> n
```

* `list.csv` のヘッダーを除いた n 行目を読み取り、適切な batch job を投げます
* 現状は `FugakuCN` と `Fugaku` 向けで、将来的に対応システムが追加される予定です

---

## 7. 変更のコミットと PR 作成

```bash
# 変更をステージング
git add programs/<code>/

# コミット
git commit -m "Add new app <code>"

# 自分の fork に push
git push origin <code>
```

* GitHub 上で自分のブランチから **元のリポジトリ** に対して PR を作成します
* PR には以下を記載するとレビューしやすくなります：

  * 新しいアプリの名前
  * 確認済みのシステム / 環境

---

## 8. 注意事項

* CI/CD のパイプラインでは各パイプラインごとに独立したディレクトリが作成されるため、ビルドや結果ファイルの衝突は基本的に起きません。
* build.shやrun.sh内部で Git リポジトリを clone する場合は、ディレクトリの衝突に注意してください。
