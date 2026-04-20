# CI Execution Control / CI実行制御

この文書は、BenchKit における GitHub Actions と GitLab CI の発火条件・運用方針を説明します。

This document describes how BenchKit controls GitHub Actions and GitLab CI execution.

BenchKit では、GitHub を公開開発リポジトリとして使い、GitLab CI を重いベンチマーク実行に使います。基本方針は、pull request では重いCIを自動発火させず、必要な場合にmaintainerが明示的にGitLab CIを起動することです。

BenchKit uses GitHub as the public development repository and GitLab CI for benchmark execution. The default policy is to keep pull requests lightweight and run heavy benchmark CI only when a maintainer explicitly starts it.

## GitHub Workflows / GitHubワークフロー

| Workflow | Trigger / 発火条件 | Purpose / 目的 |
|---|---|---|
| `GitLab Manual CI` | Manual `workflow_dispatch` / 手動実行 | Runs GitLab benchmark CI for a selected repository ref / 指定したrefに対してGitLabベンチマークCIを実行する |
| `Sync protected branches to GitLab` | Pushes to `develop` or `main` / `develop`または`main`へのpush | Mirrors protected branches to GitLab without starting GitLab CI / GitLab CIを発火させずに保護ブランチをGitLabへ同期する |
| `Guard main PR source` | Pull requests to `main` / `main`宛PR | Allows only upstream `develop` to target `main` / upstreamの`develop`から`main`へのPRだけを許可する |
| `Result Server Tests` | Result server related changes / result server関連変更 | Runs result server tests / result serverのテストを実行する |

## Pull Request Policy / Pull Request方針

`develop` 宛のpull requestはGitHub上でレビューします。

Pull requests to `develop` are reviewed on GitHub.

通常、pull requestは重いGitLabベンチマークCIを自動起動しません。これは、広範な変更や探索的な変更ごとにHPC資源・site固有runner資源を消費しないためです。

By default, pull requests do not automatically start heavy GitLab benchmark CI. This avoids burning HPC or site-specific runner resources for every contribution, especially broad or exploratory changes.

ベンチマーク検証が必要な場合は、maintainerが手動でGitLab benchmark CIを起動します。

Maintainers may run GitLab benchmark CI manually when a pull request needs benchmark validation.

## Manual GitLab CI / 手動GitLab CI

`GitLab Manual CI` はGitHub Actions UIから手動で起動します。

`GitLab Manual CI` is started from the GitHub Actions UI:

```text
Actions -> GitLab Manual CI -> Run workflow
```

入力項目は以下です。

The workflow accepts these inputs:

| Input / 入力 | Description / 説明 | Example / 例 |
|---|---|---|
| `target_ref` | Branch, tag, or SHA in the upstream repository to test / upstreamリポジトリ内でテストするbranch、tag、SHA | `feature/my-change`, `ci/pr-123`, `develop` |
| `code` | BenchKit program filter / BenchKitプログラムのフィルタ | `qws,genesis` |
| `system` | System filter used by BenchKit and BenchPark / BenchKitとBenchParkで使うsystemフィルタ | `FugakuLN,MiyabiG` |
| `app` | BenchPark application filter / BenchParkアプリケーションのフィルタ | `osu-micro-benchmarks` |
| `benchpark` | Run the BenchPark path together with BenchKit / BenchKitとBenchParkの両方を実行 | `true` |
| `park_only` | Run only the BenchPark path / BenchParkのみ実行 | `true` |
| `park_send` | Run the BenchPark send-only path / BenchParkの送信系のみ実行 | `true` |

このworkflowは以下を行います。

The workflow:

- `target_ref`をupstream GitHubリポジトリからcheckoutします。
- Checks out `target_ref` from the upstream GitHub repository.
- その内容を`github/manual-<run-id>`という一時GitLabブランチへpushします。
- Pushes it to a temporary GitLab branch named `github/manual-<run-id>`.
- push時には`ci.skip`を使い、pushそのものではGitLab pipelineを起動しません。
- Uses `ci.skip` for that push so the push itself does not start a full GitLab pipeline.
- GitLab Pipeline APIを使ってpipelineを明示的に起動します。
- Starts a GitLab pipeline through the GitLab Pipeline API.
- `code`, `system`, `app`, `park_only`, `park_send`などの指定変数を渡します。
- Passes the selected scope variables such as `code`, `system`, `app`, `park_only`, and `park_send`.
- GitLab pipelineの完了を待ちます。
- Waits for the GitLab pipeline to finish.
- 実行後、一時GitLabブランチを削除します。
- Removes the temporary GitLab branch after the run.

`target_ref`はupstreamリポジトリ内のbranch、tag、SHAを指定する想定です。forkからのpull requestをGitLab CIで試す場合は、maintainerがまずupstreamリポジトリ側に`ci/pr-123`のような信頼済み一時ブランチを作り、そのブランチに対して`GitLab Manual CI`を実行します。

`target_ref` is intended to refer to a branch, tag, or SHA in the upstream repository. For fork pull requests, a maintainer should first create a trusted temporary branch in the upstream repository, such as `ci/pr-123`, and then run `GitLab Manual CI` against that branch.

## Protected Branch Synchronization / 保護ブランチ同期

`Sync protected branches to GitLab` は以下へのpush時だけ動作します。

`Sync protected branches to GitLab` runs only on pushes to:

- `develop`
- `main`

feature branchへのpushではGitLab同期は行いません。

Feature branch pushes do not trigger GitLab synchronization.

この同期workflowは、`develop`、`main`、tagを`ci.skip`付きでGitLabへmirrorします。これによりGitLab側の履歴は追従しますが、GitLab CIは自動起動しません。

The sync workflow mirrors `develop`, `main`, and tags to GitLab with `ci.skip`. This keeps GitLab history aligned without starting GitLab CI automatically.

通常の運用では、pull requestが`develop`へmergeされた後、または`develop`が`main`へmergeされた後に同期が行われます。

In the normal workflow, synchronization happens after a pull request is merged into `develop`, or after `develop` is merged into `main`.

## Main Branch Pull Requests / mainブランチへのPull Request

`main` は `develop` からの昇格先として使います。

`main` is intended to receive changes from `develop`.

`Guard main PR source` は、`main` 宛のpull requestについて、source branchがupstreamリポジトリの`develop`である場合だけ許可します。それ以外の`main`宛pull requestはこのcheckで失敗します。

`Guard main PR source` allows pull requests to `main` only when the source branch is the upstream repository's `develop` branch. Other pull requests targeting `main` fail this guard check.

## GitLab CI Scope Controls / GitLab CIの実行範囲制御

GitLab CIは、pipeline variablesとcommit message tagによる明示的な実行範囲制御をサポートします。

GitLab CI supports explicit scope controls through pipeline variables and commit message tags.

現在の推奨はpipeline variablesです。`GitLab Manual CI`はpipeline variablesを使います。commit message tagによる制御は互換性のため当面残しますが、将来的には廃止または縮小する可能性があります。

The recommended mechanism is pipeline variables. `GitLab Manual CI` uses pipeline variables. Commit-message based controls are kept for compatibility for now, but may be removed or reduced in the future.

### Pipeline Variables / Pipeline変数

| Variable / 変数 | Description / 説明 | Example / 例 |
|---|---|---|
| `system` | System filter used by BenchKit and BenchPark / BenchKitとBenchParkで使うsystemフィルタ | `MiyabiG,MiyabiC,RC_GENOA` |
| `code` | BenchKit program filter / BenchKit programフィルタ | `qws,genesis` |
| `app` | BenchPark application filter / BenchPark applicationフィルタ | `osu-micro-benchmarks` |
| `benchpark` | Enable the BenchPark pipeline path / BenchPark pipeline pathを有効化 | `true` |
| `park_only` | Run BenchPark and skip the normal BenchKit matrix / BenchParkのみ実行し通常BenchKit matrixをスキップ | `true` |
| `park_send` | Run BenchPark result sending path and skip the normal BenchKit matrix / BenchPark送信系を実行し通常BenchKit matrixをスキップ | `true` |

### Branching Behavior / 分岐パターン

| Variables / 変数 | BenchKit | BenchPark | Description / 説明 |
|---|---|---|---|
| `code=scale-letkf` | `scale-letkf` only / `scale-letkf`のみ | Skip / スキップ | Run a selected BenchKit code / 指定BenchKit codeのみ実行 |
| `park_only=true` | Skip / スキップ | All apps / 全app | Run BenchPark only / BenchParkのみ実行 |
| `park_only=true app=osu-micro-benchmarks` | Skip / スキップ | OSU only / OSUのみ | Run one BenchPark app / BenchParkの特定appのみ実行 |
| `park_send=true` | Skip / スキップ | All apps send-only / 全app送信のみ | Re-send BenchPark results / BenchPark結果を再送信 |
| `park_send=true app=osu-micro-benchmarks` | Skip / スキップ | OSU send-only / OSU送信のみ | Re-send one BenchPark app / BenchParkの特定app結果を再送信 |
| `benchpark=true` | All / 全実行 | All apps / 全app | Run both BenchKit and BenchPark / BenchKitとBenchParkの両方を実行 |
| `benchpark=true code=qws app=osu-micro-benchmarks` | `qws` only / `qws`のみ | OSU only / OSUのみ | Run both paths with filters / 両方をフィルタ付きで実行 |
| No variables / 変数なし | All / 全実行 | Skip / スキップ | Normal BenchKit CI / 通常のBenchKit CI |

`code`はBenchKit用のフィルタです。`code`だけを指定してもBenchPark jobは有効化されません。BenchParkを動かすには、`benchpark=true`、`park_only=true`、`park_send=true`のいずれかを指定してください。

`code` is a BenchKit filter. Setting only `code` does not enable BenchPark jobs. To run BenchPark, set `benchpark=true`, `park_only=true`, or `park_send=true`.

### Legacy Commit Message Tags / 旧コミットメッセージタグ

commit message tagによる制御はlegacy扱いです。新しい運用では、GitHub Actions UIの`GitLab Manual CI`入力、またはGitLab Pipeline APIのvariablesを使ってください。

Commit-message based controls are legacy. For new operation, use `GitLab Manual CI` inputs in the GitHub Actions UI or GitLab Pipeline API variables.

| Tag / タグ | BenchKit | BenchPark | Purpose / 用途 |
|---|---|---|---|
| No tag / タグなし | Run / 実行 | Skip / スキップ | Normal BenchKit benchmark execution / 通常のBenchKitベンチマーク実行 |
| `[code:<code>]` | Run selected code / 指定codeのみ実行 | Skip / スキップ | Limit BenchKit jobs to one or more programs / BenchKit jobを特定programに限定 |
| `[system:<system>]` | Run selected system / 指定systemのみ実行 | Skip / スキップ | Limit BenchKit jobs to one or more systems / BenchKit jobを特定systemに限定 |
| `[park-only]` | Skip / スキップ | Run / 実行 | BenchPark development or testing / BenchPark開発・テスト |
| `[park-send]` | Skip / スキップ | Send only / 送信のみ | BenchPark result conversion and sending / BenchPark結果変換・送信 |
| `[benchpark]` | Run / 実行 | Run / 実行 | Run BenchKit and BenchPark paths / BenchKitとBenchParkの両方を実行 |
| `[skip ci]` or `[ci skip]` | Skip / スキップ | Skip / スキップ | Skip CI when supported by the CI service / CIサービスが対応する場合にCIをスキップ |

Examples / 例:

```bash
# Run selected systems only / 指定systemのみ実行
git commit -m "Fix run settings [system:MiyabiG,MiyabiC,RC_GENOA]"

# Run selected programs only / 指定programのみ実行
git commit -m "Update qws [code:qws,genesis]"

# Combine system and code filters / systemとcodeを組み合わせる
git commit -m "Test qws on MiyabiG [system:MiyabiG] [code:qws]"

# Run BenchPark only / BenchParkのみ実行
git commit -m "Fix BenchPark runner [park-only]"

# Run BenchPark result conversion and sending only / BenchPark結果変換・送信のみ実行
git commit -m "Fix result converter [park-send]"

# Skip CI when supported by the CI service / CIサービスが対応する場合にCIをスキップ
git commit -m "Update docs [skip ci]"
```

## Automatic Skip Rules / 自動スキップルール

GitLab pipelineは、変更がドキュメントやresult server関連ファイルに限定される場合、`.gitlab-ci.yml`のrulesに従ってベンチマーク実行を避けます。

The GitLab pipeline avoids benchmark execution when changes are limited to documentation or result server files, according to the active rules in `.gitlab-ci.yml`.

現在のskip寄りのpatternには以下があります。

Current skip-oriented patterns include:

- `*.md`
- `result_server/**/*`

## Contributor Guidance / コントリビュータ向け注意

不要な重いCI実行を避けるため、以下を推奨します。

To avoid unnecessary heavy CI runs:

- ドキュメントのみの変更は、ベンチマークアプリ変更と分けてください。
- Keep documentation-only changes separate from benchmark application changes.
- 関係のない複数programの変更は、可能なら別々のpull requestに分けてください。
- Keep unrelated benchmark program changes in separate pull requests when possible.
- ベンチマーク検証が必要な場合だけ`GitLab Manual CI`を使ってください。
- Use `GitLab Manual CI` only when benchmark validation is needed.
- 広範な検証が不要な場合は、`code`や`system`フィルタを明示してください。
- Use explicit `code` and `system` filters for manual GitLab runs when broad validation is not needed.

pull request、issue、commit message、CI設定には、secretやprivate credentialを書かないでください。

Do not include secrets or private credentials in pull requests, issues, commit messages, or CI configuration.
