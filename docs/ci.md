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
| `Result Server Tests` | Result server, portal metadata, site config, or portal upload helper changes / result server、portal metadata、site config、portal upload helper関連変更 | Runs site config preflight and result server tests / site config preflightとresult serverのテストを実行する |

## GitLab Secrets / GitLab secret

GitHub ActionsからGitLabへpushまたはpipeline triggerを行うworkflowでは、以下のsecretを使います。

Workflows that push to GitLab or trigger GitLab pipelines use these secrets:

| Secret | Format / 形式 | Purpose / 目的 |
|---|---|---|
| `GITLAB_TOKEN` | GitLab token with push and pipeline API access / pushとpipeline APIに使えるGitLab token | Authenticates Git operations and Pipeline API calls / Git操作とPipeline API呼び出しを認証する |
| `GITLAB_REPO` | Scheme-less `host/path` such as `gitlab.example.com/group/project.git` / `gitlab.example.com/group/project.git` のようなschemeなし`host/path` | Selects the GitLab project used by sync and manual CI / syncとmanual CIが使うGitLab projectを指定する |

`GITLAB_REPO` に `https://` や `http://` は付けません。`GitLab Manual CI` と `Sync protected branches to GitLab` は同じ形式を検証して使います。

Do not include `https://` or `http://` in `GITLAB_REPO`. `GitLab Manual CI` and `Sync protected branches to GitLab` validate and use the same format.

この検証は `.github/actions/prepare-gitlab-repo` に集約しています。

This validation is centralized in `.github/actions/prepare-gitlab-repo`.

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

保護ブランチ同期は`ci.skip`付きでGitLabへpushするため、これらのskip rulesは主にGitLab上で直接pipelineを起動した場合、または`GitLab Manual CI`がPipeline APIで明示起動した場合の保険として効きます。

Protected-branch synchronization pushes to GitLab with `ci.skip`, so these skip rules mainly matter when a GitLab pipeline is started directly on GitLab or explicitly through the Pipeline API by `GitLab Manual CI`.

現在のskip寄りのpatternには以下があります。

Current skip-oriented patterns include:

- `*.md`
- `docs/**/*`
- `result_server/**/*`
- `config/system_info.csv`

`system_info.csv` is the public portal catalog. Every system listed there must also be registered in `system.csv` and reference a queue defined in `queue.csv`. The reverse is intentionally not required: private or development-only systems may exist in `system.csv` / `queue.csv` without being exposed in `system_info.csv`.

`system_info.csv` はportalでユーザーに見える公開catalogです。そこに載せたsystemは必ず `system.csv` に登録され、`queue.csv` に定義されたqueueを参照する必要があります。逆方向は必須ではありません。開発用・非公開用のsystemやqueueは、`system_info.csv` に公開せず `system.csv` / `queue.csv` にだけ存在してよいです。

The app support matrix, partial support, missing app entrypoints, and unknown systems in `list.csv` are shown in `/results/usage` for operational visibility, but they are not CI-failing checks at this stage because application readiness varies by app and rollout phase.

app support matrix、partial support、app entrypoint不足、`list.csv` 内の未知systemは、運用 visibility のため `/results/usage` に表示します。ただしアプリごとの準備状況や導入段階がばらばらなため、現時点では CI failure にはしません。

## Expected CI Behavior by Change Type / 変更種別ごとの期待CI動作

| Change type / 変更種別 | GitHub Actions | GitLab benchmark CI | Notes / 補足 |
|---|---|---|---|
| Root Markdown or `docs/**/*` only / root Markdownまたは`docs/**/*`のみ | No benchmark-specific GitHub workflow / ベンチマーク用GitHub workflowなし | Skipped by `.gitlab-ci.yml` rules / `.gitlab-ci.yml` rulesでskip | Keep docs-only changes separate from benchmark logic changes / docsのみの変更はbenchmark logic変更と分ける |
| `result_server/**/*` / `result_server/**/*` | `Result Server Tests` | Skipped by `.gitlab-ci.yml` rules / `.gitlab-ci.yml` rulesでskip | Portal regressions should be caught by lightweight Python tests / portal回帰はlightweight Python testで捕捉する |
| Portal metadata `config/system_info.csv` / portal表示メタデータ`config/system_info.csv` | `Result Server Tests`, including site config preflight / site config preflightを含む`Result Server Tests` | Skipped by `.gitlab-ci.yml` rules / `.gitlab-ci.yml` rulesでskip | Public systems listed in `system_info.csv` must also exist in `system.csv` and reference a queue defined in `queue.csv` / `system_info.csv`に載せる公開systemは`system.csv`にも存在し、`queue.csv`定義済みqueueを参照する必要がある |
| Portal upload helper / portal upload helper | `Result Server Tests` when covered by its path filter / path filter対象なら`Result Server Tests` | Not automatic for pull requests; runs only if a maintainer starts `GitLab Manual CI` / pull requestでは自動起動せず、maintainerが`GitLab Manual CI`を起動した場合のみ実行 | Upload helpers live under `scripts/**/*`, so manual benchmark validation may include them / upload helperは`scripts/**/*`配下なので手動benchmark検証の対象になりうる |
| Benchmark app, shared scripts, `config/system.csv`, or `config/queue.csv` / benchmark app、共通script、`config/system.csv`、`config/queue.csv` | Normal GitHub review checks only / 通常のGitHub review checkのみ | Run through `GitLab Manual CI` when maintainer starts it / maintainerが`GitLab Manual CI`を起動した場合に実行 | Use `code` and `system` filters when broad validation is unnecessary / 広範な検証が不要なら`code`と`system`を指定する |
| GitHub workflow/action / GitHub workflow/action | Workflow-specific checks when paths match / path一致時にworkflowごとのcheck | Not required by itself / それ単体では不要 | GitHub workflow/action changes affect API-calling or sync control logic. Validate them on the GitHub side; they are pushed to GitLab with `ci.skip` during protected-branch sync / GitHub workflow/action変更はAPI呼び出しやsync制御に影響する。GitHub側で確認する。protected-branch syncでは`ci.skip`付きでGitLabへpushされる |
| `.gitlab-ci.yml` / `.gitlab-ci.yml` | Normal GitHub review checks only / 通常のGitHub review checkのみ | Run through `GitLab Manual CI` when a maintainer needs to validate GitLab pipeline behavior / GitLab pipeline挙動の検証が必要な場合にmaintainerが`GitLab Manual CI`で実行 | This file defines GitLab benchmark pipeline behavior / このファイルはGitLab benchmark pipeline挙動を定義する |

## Representative Change Sets / 代表的な変更セット

以下は、pull requestを分けるか、GitLab benchmark CIを手動実行するかを判断するための代表例です。

Use these examples when deciding whether to split a pull request or start GitLab benchmark CI manually.

| Example change set / 変更例 | Expected checks / 期待される確認 | GitLab benchmark expectation / GitLab benchmark期待値 |
|---|---|---|
| `docs/ci.md` only / `docs/ci.md`のみ | Review the documentation diff / docs差分をreview | No benchmark run. Direct/manual GitLab pipelines should skip by rules / benchmark不要。直接/手動GitLab pipelineではrulesでskipされる想定 |
| `result_server/routes/usage.py` and `result_server/templates/*.html` / `result_server/routes/usage.py`と`result_server/templates/*.html` | `Result Server Tests` should run / `Result Server Tests`が動く | No benchmark run unless a maintainer intentionally starts one / maintainerが意図して起動しない限りbenchmark不要 |
| `config/system_info.csv` only / `config/system_info.csv`のみ | `Result Server Tests` should verify public site config consistency / 公開site config整合性を`Result Server Tests`で確認 | No benchmark run because this file is portal display metadata / portal表示metadataなのでbenchmark不要 |
| `config/system.csv` or `config/queue.csv` for a public system / 公開system向けの`config/system.csv`または`config/queue.csv` | `Result Server Tests` should run the site config preflight / `Result Server Tests`でsite config preflightを実行 | Start `GitLab Manual CI` too when benchmark execution behavior needs validation / benchmark実行挙動の検証が必要なら`GitLab Manual CI`も起動 |
| `scripts/result_server/send_results.sh` only / `scripts/result_server/send_results.sh`のみ | `Result Server Tests` should run when the path filter matches / path filter対象なら`Result Server Tests`が動く | Manual GitLab CI is optional and only needed if upload behavior affects benchmark operation / upload挙動がbenchmark運用に影響する場合だけ手動GitLab CIを検討 |
| `programs/qws/**/*` or `scripts/job/**/*` / `programs/qws/**/*`または`scripts/job/**/*` | Normal GitHub review checks / 通常のGitHub review check | Start `GitLab Manual CI` when benchmark validation is needed, preferably with explicit `code` and `system` filters / benchmark検証が必要なら`code`と`system`を明示して`GitLab Manual CI`を起動 |
| `.github/workflows/sync-to-gitlab.yml` or `.github/actions/prepare-gitlab-repo/action.yml` / `.github/workflows/sync-to-gitlab.yml`または`.github/actions/prepare-gitlab-repo/action.yml` | Validate on the GitHub Actions side / GitHub Actions側で確認 | Not a GitLab benchmark trigger by itself. Protected-branch sync pushes it with `ci.skip` / それ単体ではGitLab benchmark起動対象ではない。protected-branch syncでは`ci.skip`付きでpushされる |
| `.gitlab-ci.yml` / `.gitlab-ci.yml` | Review the GitLab rule diff carefully / GitLab rule差分を慎重にreview | Start `GitLab Manual CI` if rule behavior itself needs validation / rule挙動そのものの検証が必要なら`GitLab Manual CI`を起動 |

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
