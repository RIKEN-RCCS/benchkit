# 拠点追加手順（拠点管理者向け）

このドキュメントは、BenchKit に新しいベンチマーク実行拠点を追加する手順を拠点管理者向けにまとめたものです。
GitLab Runner と Jacamar-CI をユーザ権限でセットアップし、CI/CD パイプラインからバッチジョブを投入できるようにするまでを説明します。

## 目次

1. [前提条件](#1-前提条件)
2. [ディレクトリ構成](#2-ディレクトリ構成)
3. [GitLab Runner のインストール](#3-gitlab-runner-のインストール)
4. [Jacamar-CI のビルド・インストール](#4-jacamar-ci-のビルドインストール)
5. [カスタムランナースクリプトの作成](#5-カスタムランナースクリプトの作成)
6. [ランナーの登録](#6-ランナーの登録)
7. [Jacamar 用ランナーの設定](#7-jacamar-用ランナーの設定)
8. [config.toml の設定](#8-configtoml-の設定)
9. [BenchKit への拠点登録](#9-benchkit-への拠点登録)
10. [ランナーの常駐化（systemd user mode）](#10-ランナーの常駐化systemd-user-mode)
11. [トラブルシューティング](#11-トラブルシューティング)

---

## 1. 前提条件

- 対象システムのログインノードにSSHアクセスできること
- ユーザ権限でソフトウェアをビルド・インストールできること
- GitLab プロジェクトの Runner 登録トークンを取得済みであること
- 以下のツールが利用可能であること：
  - `git`, `curl`, `make`, `gcc`/`g++`
  - （環境によっては）`gperf`, `libseccomp` のビルドが必要

---

## 2. ディレクトリ構成

ARM系とx86系で共有ボリュームをマウントしている環境では、アーキテクチャ別にディレクトリを分けます。

```bash
# x86系
mkdir -p gitlab-runner_jacamar-ci_amd

# ARM系
mkdir -p gitlab-runner_jacamar-ci_arm
```

以降、作業ディレクトリを `$BASE_DIR` として説明します：
```bash
export BASE_DIR="$PWD/gitlab-runner_jacamar-ci_amd"  # x86の場合
# export BASE_DIR="$PWD/gitlab-runner_jacamar-ci_arm"  # ARMの場合
cd "$BASE_DIR"
```

最終的なディレクトリ構成：
```
$BASE_DIR/
├── bin/
│   ├── gitlab-runner     # GitLab Runner バイナリ
│   └── jacamar           # Jacamar-CI バイナリ
├── builds/               # ビルド作業ディレクトリ
├── cache/                # キャッシュディレクトリ
├── config.toml           # Runner 設定ファイル
├── custom-config.toml    # Jacamar 設定ファイル
├── config.sh             # カスタムランナー: config
├── prepare.sh            # カスタムランナー: prepare
├── run.sh                # カスタムランナー: run
└── cleanup.sh            # カスタムランナー: cleanup
```

---

## 3. GitLab Runner のインストール

ユーザ権限でバイナリをダウンロードします。

### x86_64 の場合
```bash
mkdir -p "$BASE_DIR/bin"
curl -L --output "$BASE_DIR/bin/gitlab-runner" \
  https://gitlab-runner-downloads.s3.amazonaws.com/v18.5.0/binaries/gitlab-runner-linux-amd64
chmod +x "$BASE_DIR/bin/gitlab-runner"
```

### ARM64 の場合
```bash
mkdir -p "$BASE_DIR/bin"
curl -L --output "$BASE_DIR/bin/gitlab-runner" \
  https://gitlab-runner-downloads.s3.amazonaws.com/v18.5.0/binaries/gitlab-runner-linux-arm64
chmod +x "$BASE_DIR/bin/gitlab-runner"
```

> **Warning**: `latest` は使わず、必ずバージョンを固定してください。過去に `latest` で取得したバージョンにバグがあり動作しなかったことがあります。動作確認済みのバージョン（例: `v18.5.0`）を明示的に指定することを強く推奨します。

---

## 4. Jacamar-CI のビルド・インストール

### 基本パターン（libseccomp 不要な環境）

```bash
cd "$BASE_DIR"

# Go のインストール
export GO_PKG=go1.25.0.linux-amd64.tar.gz  # ARM: go1.25.0.linux-arm64.tar.gz
curl -OL "https://go.dev/dl/${GO_PKG}"
tar -C "$PWD" -xzf "${GO_PKG}"
rm "${GO_PKG}"

export GOROOT="$PWD/go"
export GOBIN="$GOROOT/bin"
export PATH="$GOBIN:$PATH"

# Jacamar のビルド
git clone https://gitlab.com/ecp-ci/jacamar-ci.git

# サイト固有パッチの適用（必要な場合のみ、後述）
# cp tools.go jacamar-ci/internal/executors/pbs/

cd jacamar-ci

export CC=gcc
export CXX=g++
export CGO_ENABLED=1

make build
make install PREFIX="$BASE_DIR"

# 後片付け
cd "$BASE_DIR"
rm -rf jacamar-ci go
```

### サイト固有パッチについて

一部のジョブスケジューラ環境では、Jacamar のデフォルト実装がそのまま動作しない場合があります。
例えば Miyabi の PBS 環境では、`qstat` の出力形式やジョブ完了判定のロジックが標準と異なるため、
`internal/executors/pbs/tools.go` を差し替える必要がありました。

主な変更点（Miyabi PBS の例）：
- `qstat` の JSON 出力が使えないため、テキスト形式でパース
- ジョブ完了判定: `qstat` 出力にジョブIDが含まれなくなったら完了と判定
- `Exit_status` の取得: `-H -f` オプションで履歴から抽出（テキスト形式）
- ジョブが履歴に残らない場合は正常終了と見なす

パッチの適用方法：
```bash
git clone https://gitlab.com/ecp-ci/jacamar-ci.git

# パッチファイルを配置してからビルド
cp tools.go jacamar-ci/internal/executors/pbs/

cd jacamar-ci
make build
make install PREFIX="$BASE_DIR"
```

> **Note**: パッチが必要かどうかは、対象システムで `qstat -f -F json <jobid>` が正常に動作するかで判断できます。JSON出力がサポートされていない場合はパッチが必要です。

### 拡張パターン（gperf → libseccomp が必要な環境）

一部の環境では libseccomp が必要です。その場合は gperf → libseccomp → Jacamar の順にビルドします。

```bash
cd "$BASE_DIR"
set -euo pipefail

# --- 変数定義 ---
WORKDIR="${PWD}"
GPERF_VER="3.1"
SEC_VER="2.5.5"
GO_PKG="go1.25.0.linux-amd64.tar.gz"  # ARM: go1.25.0.linux-arm64.tar.gz

LOCAL_PREFIX="${WORKDIR}/local"
SEC_PREFIX="${LOCAL_PREFIX}/libseccomp"
GPERF_PREFIX="${LOCAL_PREFIX}/gperf"
GOROOT="${WORKDIR}/go"

mkdir -p "${LOCAL_PREFIX}"

# --- 1. Go ---
curl -sSL "https://go.dev/dl/${GO_PKG}" -o "${GO_PKG}"
tar -C "${WORKDIR}" -xzf "${GO_PKG}" && rm -f "${GO_PKG}"
export GOROOT GOBIN="${GOROOT}/bin" PATH="${GOROOT}/bin:${PATH}"

# --- 2. gperf ---
curl -sSL "https://ftp.gnu.org/gnu/gperf/gperf-${GPERF_VER}.tar.gz" -o gperf.tar.gz
tar xf gperf.tar.gz && rm gperf.tar.gz
cd "gperf-${GPERF_VER}"
./configure --prefix="${GPERF_PREFIX}"
make -j$(nproc) && make install
cd "${WORKDIR}"
export PATH="${GPERF_PREFIX}/bin:${PATH}"

# --- 3. libseccomp ---
curl -sSL "https://github.com/seccomp/libseccomp/releases/download/v${SEC_VER}/libseccomp-${SEC_VER}.tar.gz" -o libseccomp.tar.gz
tar xf libseccomp.tar.gz && rm libseccomp.tar.gz
cd "libseccomp-${SEC_VER}"
./configure --prefix="${SEC_PREFIX}" --disable-shared
make -j$(nproc) && make install
cd "${WORKDIR}"
export PKG_CONFIG_PATH="${SEC_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="${SEC_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="${SEC_PREFIX}/lib:${LIBRARY_PATH:-}"
export CPATH="${SEC_PREFIX}/include:${CPATH:-}"

# --- 4. Jacamar ---
git clone https://gitlab.com/ecp-ci/jacamar-ci.git
cd jacamar-ci
export CC=gcc CXX=g++ CGO_ENABLED=1
make build
make install PREFIX="${WORKDIR}"

# --- 5. 後片付け ---
cd "${WORKDIR}"
rm -rf jacamar-ci "gperf-${GPERF_VER}" "libseccomp-${SEC_VER}" go
```

---

## 5. カスタムランナースクリプトの作成

フロントエンド用ランナーには4つのスクリプトが必要です。以下を `$BASE_DIR` に作成してください。

### `config.sh` - ジョブ設定
```bash
#!/usr/bin/env bash
set -e

BASE_DIR="/path/to/gitlab-runner_jacamar-ci_amd"  # ← 実際のパスに変更
BASE_BUILD_DIR="${BASE_DIR}/builds"
BASE_CACHE_DIR="${BASE_DIR}/cache"

SLUG="${CUSTOM_ENV_CI_PROJECT_PATH_SLUG:-unknown}"
JOB_ID="${CUSTOM_ENV_CI_JOB_ID:-$$}"

UNIQUE_BUILD_DIR="${BASE_BUILD_DIR}/${SLUG}/job_${JOB_ID}"
UNIQUE_CACHE_DIR="${BASE_CACHE_DIR}/${SLUG}/job_${JOB_ID}"

cat <<EOS
{
  "builds_dir": "${UNIQUE_BUILD_DIR}",
  "cache_dir": "${UNIQUE_CACHE_DIR}",
  "builds_dir_is_shared": false,
  "hostname": "runner-${JOB_ID}",
  "driver": {
    "name": "custom-runner",
    "version": "v1.0"
  },
  "job_env": {
    "CUSTOM_RUNNER_JOB_ID": "${JOB_ID}",
    "CUSTOM_RUNNER_PROJECT_SLUG": "${SLUG}",
    "CUSTOM_UNIQUE_BUILD_DIR": "${UNIQUE_BUILD_DIR}",
    "CUSTOM_UNIQUE_CACHE_DIR": "${UNIQUE_CACHE_DIR}",
    "CUSTOM_DIR": "${BASE_DIR}"
  }
}
EOS
```

### `prepare.sh` - ジョブ準備（何もしない）
```bash
#!/usr/bin/env bash
set -euo pipefail
exit 0
```

### `run.sh` - ジョブ実行
```bash
#!/usr/bin/bash
source ~/.bashrc
set -eo pipefail
exec "$@"
```

### `cleanup.sh` - ジョブ後片付け
```bash
#!/bin/bash
set -e

LOGFILE="${CUSTOM_DIR}/custom_cleanup.log"
echo "CLEANUP STARTED at $(date)" >> "$LOGFILE"
echo "CUSTOM_ENV_CI_JOB_ID=$CUSTOM_ENV_CI_JOB_ID" >> "$LOGFILE"

BUILD_DIR="${CUSTOM_UNIQUE_BUILD_DIR}"
CACHE_DIR="${CUSTOM_UNIQUE_CACHE_DIR}"

[ -n "$BUILD_DIR" ] && [ -d "$BUILD_DIR" ] && rm -rf "$BUILD_DIR"
[ -n "$CACHE_DIR" ] && [ -d "$CACHE_DIR" ] && rm -rf "$CACHE_DIR"

echo "CLEANUP DONE at $(date)" >> "$LOGFILE"
```

すべてのスクリプトに実行権限を付与：
```bash
chmod +x "$BASE_DIR"/{config,prepare,run,cleanup}.sh
```

---

## 6. ランナーの登録

各拠点には2種類のランナーを登録します：

| ランナー | 用途 | executor |
|----------|------|----------|
| フロントエンド用 | ビルド・軽量処理 | custom（上記スクリプト） |
| Jacamar用 | バッチジョブ投入 | custom（Jacamar経由） |

### フロントエンド用ランナーの登録
```bash
"$BASE_DIR/bin/gitlab-runner" register \
  --non-interactive \
  --url "https://YOUR_GITLAB_SERVER" \
  --registration-token "YOUR_TOKEN" \
  --executor "custom" \
  --description "site-login" \
  --tag-list "your_site_login" \
  --run-untagged="false" \
  --locked="false" \
  --builds-dir "$BASE_DIR/builds" \
  --cache-dir "$BASE_DIR/cache" \
  --config "$BASE_DIR/config.toml" \
  --custom-config-exec="$BASE_DIR/config.sh" \
  --custom-prepare-exec="$BASE_DIR/prepare.sh" \
  --custom-run-exec="$BASE_DIR/run.sh" \
  --custom-cleanup-exec="$BASE_DIR/cleanup.sh"
```

### Jacamar 用ランナーの登録
```bash
"$BASE_DIR/bin/gitlab-runner" register \
  --non-interactive \
  --url "https://YOUR_GITLAB_SERVER" \
  --registration-token "YOUR_TOKEN" \
  --executor "custom" \
  --description "site-jacamar" \
  --tag-list "your_site_jacamar" \
  --run-untagged="false" \
  --locked="false" \
  --builds-dir "$BASE_DIR/builds" \
  --cache-dir "$BASE_DIR/cache" \
  --config "$BASE_DIR/config.toml" \
  --custom-config-exec="$BASE_DIR/bin/jacamar" \
  --custom-prepare-exec="$BASE_DIR/bin/jacamar" \
  --custom-run-exec="$BASE_DIR/bin/jacamar" \
  --custom-cleanup-exec="$BASE_DIR/bin/jacamar"
```

> **Note**: Jacamar 用ランナーの `--custom-*-exec` は登録時のプレースホルダです。実際の引数は `config.toml` で設定します（次セクション参照）。

---

## 7. Jacamar 用ランナーの設定

### `custom-config.toml` - Jacamar 設定ファイル

```toml
[general]
executor = "slurm"          # or "pbs", "pjm" etc.
data_dir = "/path/to/gitlab-runner_jacamar-ci_amd"
retain_logs = true

[auth]
downscope = "setuid"
user_allowlist = ["your_username"]  # ← ランナーを動かすユーザ名

[batch]
command_delay = "30s"
```

- `executor`: 拠点のジョブスケジューラに合わせて設定（`slurm`, `pbs`, `pjm` 等）
- `user_allowlist`: ユーザモードで動かすため、自分のアカウント名を記載

---

## 8. config.toml の設定

ランナー登録後に生成される `config.toml` を編集します。

### 重要: PATH の設定

`gitlab-runner` をユーザ権限でインストールした場合、`config.toml` の `[[runners]]` セクションに `environment` で PATH を通す必要があります。これがないとアーティファクト保存時にエラーになります。

```toml
[[runners]]
  environment = [
    "PATH=/path/to/gitlab-runner_jacamar-ci_amd/bin:/usr/local/bin:/usr/bin:/bin"
  ]
```

### Jacamar 用ランナーの `[runners.custom]` セクション

```toml
[runners.custom]
  config_exec = "/path/to/gitlab-runner_jacamar-ci_amd/bin/jacamar"
  config_args = [
    "--no-auth", "config",
    "--configuration", "/path/to/gitlab-runner_jacamar-ci_amd/custom-config.toml"
  ]
  prepare_exec = "/path/to/gitlab-runner_jacamar-ci_amd/bin/jacamar"
  prepare_args = ["--no-auth", "prepare"]
  run_exec = "/path/to/gitlab-runner_jacamar-ci_amd/bin/jacamar"
  run_args = ["--no-auth", "run"]
  cleanup_exec = "/path/to/gitlab-runner_jacamar-ci_amd/bin/jacamar"
  cleanup_args = [
    "--no-auth", "cleanup",
    "--configuration", "/path/to/gitlab-runner_jacamar-ci_amd/custom-config.toml"
  ]
```

---

## 9. BenchKit への拠点登録

ランナーが動作したら、BenchKit リポジトリに拠点情報を追加します。

### `config/system.csv` にシステムを追加

```csv
system,mode,tag_build,tag_run,queue,queue_group
# 既存エントリ...
# cross モード（ビルドと実行が別ノード）
NewSystem,cross,newsystem_login,newsystem_jacamar,PBS_NewSystem,default
# native モード（同一ノードでビルドと実行）
NewSystemLN,native,,newsystem_login,none,default
```

- `system`: システム名（アプリの `list.csv` から参照される）
- `mode`: `cross`（ビルドと実行が別ノード）または `native`（同一ノードで実行）
- `tag_build`: ビルド用GitLab Runnerタグ（`native`の場合は空）
- `tag_run`: 実行用GitLab Runnerタグ（`native`の場合はbuild_runジョブ用）
- `queue`: `config/queue.csv` のキュー名（ログインノードは `none`）
- `queue_group`: キューグループ名

### `config/queue.csv` にキューシステムを追加（必要な場合）

既存のキューシステム（`FJ`, `PBS_Miyabi`, `SLURM_RC`）に該当しない場合は追加：

```csv
queue,submit_cmd,template
PBS_NewSystem,qsub,"-q ${queue_group} -l select=${nodes} -l walltime=${elapse} -W group_list=your_group"
```

テンプレート内で使える変数：`${queue_group}`, `${nodes}`, `${numproc_node}`, `${nthreads}`, `${elapse}`

---

## 10. ランナーの常駐化（systemd user mode）

アーキテクチャごとに `systemctl --user` でサービスとして常駐させます。

### サービスファイルの作成

```bash
mkdir -p ~/.config/systemd/user
```

#### x86 用: `~/.config/systemd/user/gitlab-runner-amd.service`
```ini
[Unit]
Description=GitLab Runner service (user mode, amd64)
After=network.target
ConditionHost=your-login-node   # ← 実際のホスト名に変更

[Service]
ExecStart=%h/gitlab-runner_jacamar-ci_amd/bin/gitlab-runner run --config %h/gitlab-runner_jacamar-ci_amd/config.toml --working-directory %h
Restart=always
RestartSec=10
StandardOutput=append:%h/gitlab-runner_jacamar-ci_amd/gitlab-runner.log
StandardError=append:%h/gitlab-runner_jacamar-ci_amd/gitlab-runner.err

[Install]
WantedBy=default.target
```

#### ARM 用: `~/.config/systemd/user/gitlab-runner-arm.service`
```ini
[Unit]
Description=GitLab Runner service (user mode, arm64)
After=network.target
ConditionHost=your-arm-login-node   # ← 実際のホスト名に変更

[Service]
ExecStart=%h/gitlab-runner_jacamar-ci_arm/bin/gitlab-runner run --config %h/gitlab-runner_jacamar-ci_arm/config.toml --working-directory %h
Restart=always
RestartSec=10
StandardOutput=append:%h/gitlab-runner_jacamar-ci_arm/gitlab-runner.log
StandardError=append:%h/gitlab-runner_jacamar-ci_arm/gitlab-runner.err

[Install]
WantedBy=default.target
```

`ConditionHost=` を設定することで、同じホームディレクトリを複数ノードで共有していても、指定したホストでのみサービスが起動します。

### サービスの有効化・起動

```bash
# systemd にファイルを認識させる
systemctl --user daemon-reload

# 自動起動を有効化
systemctl --user enable gitlab-runner-amd.service

# 起動
systemctl --user start gitlab-runner-amd.service

# 状態確認
systemctl --user status gitlab-runner-amd.service

# ログアウト後もサービスを維持（重要）
loginctl enable-linger $LOGNAME
```

> **Note**: `loginctl enable-linger` を実行しないと、ログアウト時にサービスが停止します。

### 接続確認
GitLab の Settings → CI/CD → Runners で、登録したランナーが「online」になっていることを確認。

### テストジョブの実行
既存のアプリで新拠点のテストを行う場合：
```bash
# list.csv に新拠点の設定を追加してテスト
bash scripts/test_submit.sh qws 1
```

---

## 11. トラブルシューティング

### アーティファクト保存でエラーになる
`config.toml` の `[[runners]]` セクションに `environment` で PATH が通っているか確認：
```toml
environment = ["PATH=/path/to/gitlab-runner_jacamar-ci_amd/bin:..."]
```

### Jacamar がジョブスケジューラを見つけられない
`custom-config.toml` の `executor` が正しいか確認。対応スケジューラ：
- `slurm` - SLURM
- `pbs` - PBS/Torque
- `pjm` - PJM（富岳）

### ランナーが GitLab に接続できない
- ログインノードから GitLab サーバへの HTTPS 通信が可能か確認
- プロキシ設定が必要な場合は `config.toml` の `environment` に `https_proxy` を追加

### ARM/x86 混在環境での注意
同じ共有ボリュームを異なるアーキテクチャのマシンがマウントしている場合、必ずアーキテクチャ別のディレクトリ（`_amd` / `_arm`）を使い分けてください。バイナリの混在はランタイムエラーの原因になります。

### PBSジョブが実行されない（Jacamar-CI ジョブ監視の問題）

**症状:**
- ベンチマークジョブが実行されない
- GitLab CIログで「NFS同期問題」として現れる
- `wait_for_nfs.sh` がタイムアウト
- `results` ディレクトリやJSONファイルが作成されない

**根本原因:**
Jacamar-CI のPBSジョブ状態監視ロジックが、カスタムPBS環境に対応していない場合があります。
ジョブがQUEUED状態でも「completed」と誤判定され、実際にはジョブが実行されずに次のステップに進んでしまいます。

> **Note**: 当初「NFS同期遅延」と思われていた問題が、実際にはJacamar-CIのバグだったという事例があります（Miyabi環境）。NFS待機時間を延長しても解決しない場合は、Jacamar-CIのジョブ監視を疑ってください。

**診断方法:**
```bash
# qstat の JSON 出力が使えるか確認
qstat -F json <job_id>

# 通常形式の出力確認
qstat -f <job_id>

# ジョブ履歴の確認
qstat -H -f <job_id>
```

**解決方法:**
JSON形式の `qstat` がサポートされていない場合は、セクション4「サイト固有パッチについて」に記載の `tools.go` パッチを適用してください。

### NFS同期でファイルが見えない

**症状:**
- 計算ノードで作成された `results/*.json` がログインノードから見えない
- アーティファクト収集で「No files to upload」エラー

**対策:**
1. `custom-config.toml` の `nfs_timeout` を調整：
```toml
[batch]
command_delay = "30s"
nfs_timeout = "2m"    # 必要に応じて 5m, 10m に延長
```
2. ただし、NFS遅延が疑われる場合でも、まずJacamar-CIのジョブ監視が正常か確認すること（上記参照）

### 新システム追加時のチェックリスト

- [ ] PBSのバージョンとカスタマイズ内容を確認
- [ ] `qstat` コマンドの出力形式を確認（JSON対応の有無）
- [ ] ジョブIDの形式を確認（ホスト名付きかどうか）
- [ ] Jacamar-CI でテストジョブを実行して動作確認
- [ ] `config.toml` の `environment` で PATH が通っているか確認
- [ ] `loginctl enable-linger` が設定されているか確認
