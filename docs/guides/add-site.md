# 拠点追加手順（拠点管理者向け）

このドキュメントは、BenchKit に新しいベンチマーク実行拠点を追加する手順を拠点管理者向けにまとめたものです。
GitLab Runner と Jacamar-CI をユーザ権限でセットアップし、CI/CD パイプラインからバッチジョブを投入できるようにするまでを説明します。

## 目次

1. [前提条件](#1-前提条件)
2. [クイックセットアップ（推奨）](#クイックセットアップ推奨)
3. [ディレクトリ構成](#2-ディレクトリ構成)
4. [GitLab Runner のインストール](#3-gitlab-runner-のインストール)
5. [Jacamar-CI のビルド・インストール](#4-jacamar-ci-のビルドインストール)
6. [カスタムランナースクリプトの作成](#5-カスタムランナースクリプトの作成)
7. [ランナーの登録](#6-ランナーの登録)
8. [Jacamar 用ランナーの設定](#7-jacamar-用ランナーの設定)
9. [config.toml の設定](#8-configtoml-の設定)
10. [BenchKit への拠点登録](#9-benchkit-への拠点登録)
11. [ランナーの常駐化（systemd user mode）](#10-ランナーの常駐化systemd-user-mode)
12. [トラブルシューティング](#11-トラブルシューティング)

---

## 1. 前提条件

- 対象システムのログインノードにSSHアクセスできること
- ユーザ権限でソフトウェアをビルド・インストールできること
- GitLab プロジェクトの Runner 登録トークンを取得済みであること
- 以下のツールが利用可能であること：
  - `git`, `curl`, `make`, `gcc`/`g++`
  - （環境によっては）`gperf`, `libseccomp` のビルドが必要

---

## クイックセットアップ（推奨）

通常は `scripts/setup_site_runner.sh` を使えば、GitLab Runner の取得、Jacamar-CI のビルド、frontend runner と Jacamar runner の登録、`custom-config.toml` / `config.toml` 相当の設定、systemd user service の作成までまとめて実行できます。

`--login-token` と `--jacamar-token` には、GitLab で作成した各 runner の authentication token を指定します。URL は両 runner で共通です。

### 実行前の疎通確認

セットアップ前に、対象ログインノードから GitLab サーバへ到達できるか確認します。GitLab Runner は GitLab 側から接続されるのではなく、ログインノード上の常駐プロセスが GitLab へ job を取りに行きます。

```bash
GITLAB_URL="https://YOUR_GITLAB_SERVER"

hostname -s
getent hosts "$(printf '%s\n' "$GITLAB_URL" | sed -E 's#^https?://([^/]+).*#\1#')"

env | grep -Ei '^(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY|no_proxy|NO_PROXY)=' || true
grep -Rihn -i proxy ~/.bashrc ~/.bash_profile ~/.profile /etc/profile /etc/profile.d 2>/dev/null || true

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  curl -I --connect-timeout 5 "$GITLAB_URL"
```

direct 接続が timeout し、サイト側で proxy が指定されている場合は、その proxy で疎通確認します。

```bash
RUNNER_PROXY="http://PROXY_HOST:PORT"

curl -I --connect-timeout 5 -x "$RUNNER_PROXY" "$GITLAB_URL"
```

proxy 経由でだけ成功する場合は、`setup_site_runner.sh` 実行時に `--proxy "$RUNNER_PROXY"` を指定します。`systemd --user` のサービスはログインシェルの proxy 環境変数を継承しないことがあるため、proxy は runner の systemd unit に明示しておくのが安全です。

AMD64 ログインノードの例：

```bash
curl -fsSL https://raw.githubusercontent.com/RIKEN-RCCS/benchkit/main/scripts/setup_site_runner.sh \
  | bash -s -- \
      --arch amd64 \
      --site your_site \
      --gitlab-url https://YOUR_GITLAB_SERVER \
      --login-token "$LOGIN_RUNNER_TOKEN" \
      --jacamar-token "$JACAMAR_RUNNER_TOKEN" \
      --scheduler pbs \
      --service-host "$(hostname -s)"
```

proxy が必要な拠点では、上のコマンドに `--proxy "$RUNNER_PROXY"` を追加します。

ARM64 ログインノードでは `--arch arm64` を指定します。

よく使う指定：

- `--site your_site`
  - Runner description と、期待する tag 表示に使います
- `--login-tag` / `--jacamar-tag`
  - Runner authentication token workflow では tag は GitLab 側で設定します。このオプションはスクリプト末尾の確認表示用です
- `--scheduler pbs|slurm|pjm`
  - Jacamar の executor を指定します
- `--jacamar-repo URL`
  - Jacamar-CI の clone 元を明示します。省略時は `--scheduler pjm` の場合だけ PJM 対応 fork `https://gitlab.com/yoshifuminakamura/jacamar-ci.git` を使い、それ以外は upstream `https://gitlab.com/ecp-ci/jacamar-ci.git` を使います
- `--base-dir /path/to/gitlab-runner_jacamar-ci_amd`
  - 既定は `$HOME/gitlab-runner_jacamar-ci_amd` または `$HOME/gitlab-runner_jacamar-ci_arm`
- `--libseccomp auto|system|local|none`
  - 既定は `auto` です。利用可能な system libseccomp があれば使い、なければ gperf と libseccomp をローカルビルドします
- `--with-libseccomp`
  - `--libseccomp local` の短縮形です。常に gperf と libseccomp をローカルビルドします
- `--jacamar-pbs-tools tools.go`
  - PBS の完了判定にサイト固有パッチが必要な場合に使います
- `--unrestricted-cmd-line`
  - Jacamar の `GIT_ASKPASS` credential helper が効かず、`get_sources` で `fatal: unable to get password from user` になる場合の回避策です。runner generated command line に job token が現れる可能性があるため、単一ユーザ運用や `/proc` の閲覧制限がある環境で使ってください
- `--proxy http://PROXY_HOST:PORT`
  - runner の systemd user service に `http_proxy` / `https_proxy` / `HTTP_PROXY` / `HTTPS_PROXY` を設定します。`http://` または `https://` を省略した場合は `http://` を補います
- `--no-proxy LIST`
  - runner の systemd user service に `no_proxy` / `NO_PROXY` を設定します
- `--no-systemd` / `--no-start`
  - systemd user service を作らない、または作るだけで起動しない場合に使います

Jacamar-CI のビルドは、ログインノードのプロセス数・メモリ制限に当たりにくいよう、既定で `make -j1`、`GOMAXPROCS=1`、`GOFLAGS="-p=1 -gcflags=all=-dwarf=false"` を使います。余裕のある環境では `JACAMAR_BUILD_MAKE_JOBS`、`JACAMAR_BUILD_GOMAXPROCS`、`JACAMAR_BUILD_GOFLAGS` で上書きできます。

このスクリプトは `config.toml` の `environment` に `PATH=$BASE_DIR/bin:...` を登録時点で入れるため、アーティファクト保存時に `gitlab-runner` が見つからない問題も避けられます。以下の手動手順は、スクリプトが失敗した場合の切り分けや、サイト固有に調整したい場合の参照として使ってください。

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
├── runner-env.sh         # カスタムランナー: 共通環境初期化
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
export GOMAXPROCS=1
export GOFLAGS="-p=1 -gcflags=all=-dwarf=false"

make -j1 build
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

AOBA/NQSV のように `qstat -H` が使えない環境では、ジョブが `qstat` から消えた後に終了コードを後追い取得できない場合があります。この場合は `qsub` 直後から `qwait -w exited <jobid>` で待ち、出力される `exited N` を parse して `N != 0` を GitLab job failure として扱うパッチが必要です。`qwait` 自体の戻り値が 0 でも、ジョブの終了コードは `exited N` 側に入る点に注意してください。

パッチの適用方法：
```bash
git clone https://gitlab.com/ecp-ci/jacamar-ci.git

# パッチファイルを配置してからビルド
cp tools.go jacamar-ci/internal/executors/pbs/

cd jacamar-ci
export GOMAXPROCS=1
export GOFLAGS="-p=1 -gcflags=all=-dwarf=false"
make -j1 build
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
export GOMAXPROCS=1
export GOFLAGS="-p=1 -gcflags=all=-dwarf=false"
make -j1 build
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

### `runner-env.sh` - 共通環境初期化

`run.sh` から source される共通環境初期化ファイルです。非対話 shell でも site の module catalog やユーザの基本環境が見えるように、`/etc/profile`、`/etc/bashrc`、module 初期化ファイル、`~/.bashrc` を順に読みます。アプリごとの `build.sh` / `run.sh` は、原則として site の shell 初期化そのものではなく、必要な `module load` と実行コマンドだけを持ちます。

### `run.sh` - ジョブ実行
```bash
#!/usr/bin/env bash
RUNNER_ENV="${CUSTOM_DIR:-/path/to/gitlab-runner_jacamar-ci_amd}/runner-env.sh"
if [[ -r "${RUNNER_ENV}" ]]; then
  source "${RUNNER_ENV}"
elif [[ -r "${HOME}/.bashrc" ]]; then
  source "${HOME}/.bashrc"
fi
set -eo pipefail
exec "$@"
```

### `cleanup.sh` - ジョブ後片付け
```bash
#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/path/to/gitlab-runner_jacamar-ci_amd"  # ← 実際のパスに変更
LOGFILE="${CUSTOM_DIR:-${BASE_DIR}}/custom_cleanup.log"
echo "CLEANUP STARTED at $(date)" >> "$LOGFILE"

BUILD_DIR="${CUSTOM_UNIQUE_BUILD_DIR:-}"
CACHE_DIR="${CUSTOM_UNIQUE_CACHE_DIR:-}"

case "$BUILD_DIR" in
  "${BASE_DIR}/builds/"*) [[ -d "$BUILD_DIR" ]] && rm -rf -- "$BUILD_DIR" ;;
esac

case "$CACHE_DIR" in
  "${BASE_DIR}/cache/"*) [[ -d "$CACHE_DIR" ]] && rm -rf -- "$CACHE_DIR" ;;
esac

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
  --token "YOUR_TOKEN" \
  --executor "custom" \
  --description "site-login" \
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
  --token "YOUR_TOKEN" \
  --executor "custom" \
  --description "site-jacamar" \
  --builds-dir "$BASE_DIR/builds" \
  --cache-dir "$BASE_DIR/cache" \
  --config "$BASE_DIR/config.toml" \
  --custom-config-exec="$BASE_DIR/bin/jacamar" \
  --custom-prepare-exec="$BASE_DIR/bin/jacamar" \
  --custom-run-exec="$BASE_DIR/bin/jacamar" \
  --custom-cleanup-exec="$BASE_DIR/bin/jacamar"
```

> **Note**: Jacamar 用ランナーの `--custom-*-exec` は登録時のプレースホルダです。実際の引数は `config.toml` で設定します（次セクション参照）。
> **Note**: Runner authentication token を使う GitLab Runner 18 系の workflow では、tag、locked、run-untagged などは GitLab server 側で設定します。register コマンドに `--tag-list` や `--locked` を渡すと失敗します。

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

テンプレート内で使える変数：`${queue_group}`, `${nodes}`, `${numproc_node}`, `${nthreads}`, `${elapse}`, `${proc}`（`nodes * numproc_node`）, `${cpu_per_node}`, `${gpu_per_node}`, `${cpu_sockets}`（`nodes * cpu_per_node`）, `${gpu_cards}`（`nodes * gpu_per_node`）

`${cpu_per_node}` と `${gpu_per_node}` は `config/system_info.csv` から取得します。CPU socket 数や GPU card 数を scheduler に明示するサイトでは、`system_info.csv` の値も投入条件に使われます。

### `config/system_info.csv` に表示用メタデータを追加

Result Server や比較画面でシステム情報を見せるために、`system_info.csv` にも同じ system を追加します。

```csv
system,name,cpu_name,cpu_per_node,cpu_cores,gpu_name,gpu_per_node,memory,display_order
NewSystem,NewSystem,Example CPU,2,64,Example GPU,4,512GB,10
```

- `system`
  - `config/system.csv` や `list.csv` と同じ system 名を使います
- `name`
  - 画面表示に使う名前です
- `cpu_name`, `cpu_per_node`, `cpu_cores`
  - CPU 構成です
- `gpu_name`, `gpu_per_node`
  - GPU がある場合に設定します。GPU がない場合は `-` を使います
- `memory`
  - ノードあたりメモリ容量です
- `display_order`
  - 一覧や比較画面での表示順です

`system.csv` に追加したのに `system_info.csv` を追加しないと、実行自体は通っても UI 側で説明情報が欠けることがあります。

### BenchKit 側の責務分担

拠点追加時に迷いやすい点ですが、BenchKit では設定の置き場所を次のように分けます。

- `config/system.csv`
  - システム固有の実行モード、Runner タグ、キュー種別、キューグループを持つ
- `config/queue.csv`
  - スケジューラ投入コマンドのテンプレートを持つ
- `config/system_info.csv`
  - Result Server や比較画面に出すシステム表示情報を持つ
- `programs/<code>/list.csv`
  - アプリごとのノード数、プロセス数、スレッド数、制限時間だけを持つ
- `programs/<code>/build.sh` / `run.sh`
  - `module load`、コンパイラ、`mpirun` / `srun` / `pjsub` の使い方、affinity など、実行そのものの差異を持つ

言い換えると、`system.csv` と `queue.csv` は「どこでどう投入するか」、`system_info.csv` は「そのシステムをどう見せるか」、`list.csv` は「何条件で回すか」、`build.sh` / `run.sh` は「そのシステムでどう実行するか」の責務です。

### 接続確認の推奨順序

新しい拠点を追加したら、最初の確認は次の順番で行うと切り分けが楽です。

1. `get_sources` まで到達すること
   - GitLab Runner がオンラインで、GitLab からソース取得できることを確認します。
2. scheduler に投入できること
   - `system.csv` の `queue` と `queue_group`、`queue.csv` のテンプレートが正しいことを確認します。
3. `module load` と build が通ること
   - `build.sh` のモジュール名、コンパイラ、依存ライブラリを確認します。
4. run が `results/result` を生成すること
   - `run.sh` の launcher、affinity、引数の渡し方を確認します。
5. `result0.json` が作られること
   - `scripts/result.sh` が Result JSON を組み立てられることを確認します。
6. `send_results` まで通ること
   - API key、Result Server 接続、`results/result*.json` の配置を確認します。

最初の動作確認では、既存アプリで最小の 1 条件だけ `list.csv` に足して `scripts/test_submit.sh` で試すのが安全です。

### 典型的な失敗の切り分け

拠点追加直後に起きやすい失敗は、だいたい次の層に分けられます。

| 失敗箇所 | よくある原因 | まず見る場所 |
|---|---|---|
| `get_sources` | Runner の Git 認証、GitLab 到達性、proxy 設定 | Runner ログ、`config.toml` の `environment` |
| scheduler submit | `queue` / `queue_group` の不一致、submit template の typo | `config/system.csv`, `config/queue.csv` |
| build | `module load` の typo、コンパイラ不一致、依存ライブラリ不足 | `programs/<code>/build.sh` |
| run | `mpirun` / `srun` の引数、affinity、ノード側環境差異 | `programs/<code>/run.sh`, scheduler log |
| result 生成 | `results/result` がない、FOM 出力形式が違う、`bk_emit_*` 未使用 | `scripts/result.sh`, `scripts/bk_functions.sh` |
| send_results | API key、Result Server 接続、JSON 不足 | `scripts/result_server/send_results.sh`, Result Server log |

CI ログでは、まず「どの stage まで進んだか」を見ると切り分けが早くなります。`get_sources` 前、build 前、run 前、send_results 前で原因の層がかなり絞れます。

### 新規拠点オンボーディングのチェックリスト

- [ ] GitLab Runner または Jacamar-CI が対象ログインノードで常駐している
- [ ] GitLab の Runner 一覧で `online` になっている
- [ ] `config/system.csv` に system が追加されている
- [ ] 必要なら `config/queue.csv` に queue template が追加されている
- [ ] `config/system_info.csv` に表示用メタデータが追加されている
- [ ] 対象アプリの `build.sh` / `run.sh` に system 分岐が追加されている
- [ ] 対象アプリの `list.csv` に最小 1 条件が追加されている
- [ ] build が通る
- [ ] run が通り、`results/result` が生成される
- [ ] `result0.json` が生成される
- [ ] Result Server への送信まで通る

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
# 実際のホスト名に変更
ConditionHost=your-login-node

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
# 実際のホスト名に変更
ConditionHost=your-arm-login-node

[Service]
ExecStart=%h/gitlab-runner_jacamar-ci_arm/bin/gitlab-runner run --config %h/gitlab-runner_jacamar-ci_arm/config.toml --working-directory %h
Restart=always
RestartSec=10
StandardOutput=append:%h/gitlab-runner_jacamar-ci_arm/gitlab-runner.log
StandardError=append:%h/gitlab-runner_jacamar-ci_arm/gitlab-runner.err

[Install]
WantedBy=default.target
```

`ConditionHost=` を設定することで、同じホームディレクトリを複数ノードで共有していても、指定したホストでのみサービスが起動します。systemd の unit file では行末コメントを値として解釈するので、コメントは別行に置いてください。

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
- プロキシ設定が必要な場合は `setup_site_runner.sh --proxy` で systemd user service に proxy を明示

ログインシェルでは `curl -I https://gitlab.swc.r-ccs.riken.jp` が成功するのに、常駐ランナーが
`Checking for jobs... failed` や `lookup gitlab.swc.r-ccs.riken.jp on [::1]:53` で失敗する場合は、
`systemd --user` のサービスがログインシェルの proxy 環境変数を継承していない可能性があります。

```bash
env | grep -Ei 'proxy|http|https|no_proxy'
curl -I https://gitlab.swc.r-ccs.riken.jp
systemctl --user show gitlab-runner-<site>-amd.service -p Environment
```

`systemctl --user show` の `Environment=` が空なら、サービスに proxy を明示します。

```bash
systemctl --user edit gitlab-runner-<site>-amd.service
```

```ini
[Service]
Environment="http_proxy=http://PROXY_HOST:PORT"
Environment="https_proxy=http://PROXY_HOST:PORT"
Environment="HTTP_PROXY=http://PROXY_HOST:PORT"
Environment="HTTPS_PROXY=http://PROXY_HOST:PORT"
```

```bash
systemctl --user daemon-reload
systemctl --user restart gitlab-runner-<site>-amd.service
systemctl --user show gitlab-runner-<site>-amd.service -p Environment
```

### 計算ノードに `git` がない場合

一部の計算ノードでは、ログインノードやフロントエンドランナーでは `git` が使えても、バッチジョブ内では `git: コマンドが見つかりません` になることがあります。アプリの `run.sh` が実行時に外部ソースを clone する場合は、計算ノード側でも `git` 相当のコマンドが必要です。

Singularity/Apptainer が計算ノードで使える場合は、共有ファイルシステム上に `git` 入りコンテナと wrapper を置く方法が有効です。

```bash
BASE=/uhome/<user>/gitlab-runner_jacamar-ci_amd
SING=/path/to/singularity

mkdir -p "$BASE/containers" "$BASE/bin"
"$SING" build --sandbox "$BASE/containers/git" docker://alpine/git:latest
```

`$BASE/bin/git`:

```bash
#!/bin/bash
set -e

# GitLab Runner の get_sources はログインノード上の認証 helper を使うため、
# ホストの git がある場合はそちらへ委譲する。
if [[ -x /usr/bin/git ]]; then
  exec /usr/bin/git "$@"
fi

SING=/path/to/singularity
IMG=/uhome/<user>/gitlab-runner_jacamar-ci_amd/containers/git

exec "$SING" exec \
  --bind /mnt:/mnt \
  --bind /uhome:/uhome \
  --pwd "$PWD" \
  "$IMG" \
  git "$@"
```

```bash
chmod +x "$BASE/bin/git"
```

Jacamar 用ランナーの `config.toml` では wrapper のある `bin` を `PATH` に入れます。ただし `get_sources` までコンテナ内 `git` に置き換えると、GitLab Runner/Jacamar が生成する credential helper をコンテナ内から実行できず、`fatal: cannot exec .../pass` で失敗することがあります。上記のように、ログインノードでは `/usr/bin/git` に委譲し、計算ノードでだけコンテナ内 `git` を使う wrapper にしてください。

確認:

```bash
git --version
git ls-remote https://github.com/RIKEN-LQCD/qws.git HEAD
```

### 計算ノードから外部 proxy に届かない場合

`queue.csv` で `qsub -v http_proxy,https_proxy,HTTP_PROXY,HTTPS_PROXY` を指定していても、計算ノードからその proxy に TCP 接続できるとは限りません。例えば `git` や `curl` が `Trying PROXY_HOST...` のまま進まず、ジョブが経過時間超過で kill される場合は、proxy 変数ではなくネットワーク到達性を疑います。

計算ノードで確認:

```bash
hostname -I
ip route
cat /etc/resolv.conf 2>/dev/null || true
cat /etc/hosts 2>/dev/null || true
env | sort | egrep -i '^(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY|no_proxy|NO_PROXY)=' || true

timeout 5 bash -c '</dev/tcp/PROXY_HOST/PROXY_PORT'
echo "tcp rc=$?"

timeout 20 curl -v -I -x http://PROXY_HOST:PROXY_PORT https://github.com/
echo "curl rc=$?"
```

`tcp rc=124` は timeout、`ホストへの経路がありません` は経路なしを示します。この場合は計算ノード用の別 proxy を確認するか、実行ジョブ中の外部 `git clone` を避けます。短期回避として、ログインノードで取得したソースを共有ファイルシステム上にキャッシュし、Jacamar の `pre_build_script` で作業ディレクトリへ配置しておく方法があります。

```toml
pre_build_script = """
set -e
case "${CI_JOB_NAME:-}" in
  qws_<SITE>_*_run)
    cache=/uhome/<user>/gitlab-runner_jacamar-ci_amd/site-cache/qws
    if [ ! -d qws ]; then
      echo "[site pre_build] copying qws source from $cache"
      cp -a "$cache" qws
    fi
    test -d qws || { echo "[site pre_build] qws source is missing" >&2; exit 1; }
    ;;
esac
"""
```

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

# NQSV で qstat -H がない場合は、投入直後に qwait で終了コードを確認
qwait -w exited <job_id>
```

**解決方法:**
JSON形式の `qstat` がサポートされていない場合は、セクション4「サイト固有パッチについて」に記載の `tools.go` パッチを適用してください。
NQSV のように `qstat -H` がない場合は、`qwait -w exited <job_id>` の出力を使って終了コードを返す `tools.go` パッチを適用してください。

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
