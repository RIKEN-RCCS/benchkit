# BenchKit仕様 / BenchKit Specification

## 言語方針 / Language Policy

本書は日本語を正本とし、英語は参照用の補助訳とする。
解釈に差異がある場合は日本語版を優先する。

This document uses Japanese as the authoritative version.
The English text is provided as a supporting reference translation.
If any discrepancy exists, the Japanese version takes precedence.

## 読み方のルール / Reading Conventions

本書では、[`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md) の読み方のルールに従う。
特に、本書では以下を区別して読むことが重要である。

- 必須要件:
  追跡しなければならない情報、満たさなければならない接続条件、BenchKit が責任を持つべき事項。
- 原則:
  shell-first、ポータル中心、責務分離のような設計原則。
- 将来拡張:
  申請フォーム、自動 PR、AI 駆動最適化、MCP 連携などの拡張方向。

This document follows the reading conventions defined in [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md).
In particular, it is important here to distinguish:

- mandatory requirements:
  information that must be tracked, connection conditions that must be satisfied, and responsibilities that BenchKit must own.
- principles:
  design principles such as shell-first, portal-centered interaction, and separation of responsibilities.
- future extensions:
  directions such as request forms, automatic PR generation, AI-driven optimization, and MCP integration.

## 1. 目的 / Purpose

BenchKit は、CX基盤を構成する中核ソフトウェアであり、
継続的ベンチマーク、継続的推定、継続的フィードバックを実用的に回すための基盤ソフトウェア兼ポータルである。

BenchKit は特に以下を担う。

- ベンチマーク実行定義を保持する
- CI/CD による継続実行を生成する
- 結果および推定結果を正規化する
- ベンチマーク結果・推定結果・使用量を表示する
- 将来の申請、承認、最適化、AI 指示ワークフローへの接続点を提供する

BenchKit is a core software component of the CX Platform and serves as both infrastructure and portal for practical continuous benchmarking, continuous estimation, and continuous feedback.

BenchKit is responsible in particular for:

- holding benchmark execution definitions
- generating continuous execution through CI/CD
- normalizing benchmark and estimation outputs
- presenting benchmark results, estimation results, and usage
- providing integration points for future request, approval, optimization, and AI instruction workflows

## 1.1 文書の位置づけ / Position of This Document

本書は、[`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md) および [`CX_PLATFORM.md`](./CX_PLATFORM.md) を受けて、BenchKit 自体の責務・構成・接続点を定義する下位仕様である。

本書は、BenchKit の外にある外部サービス、外部ツール、実システムを前提とするが、
それらの内部仕様そのものではなく、BenchKit から見た責務境界と接続要件を記述する。
主要用語は [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md) の用語集に従う。

This document is a lower-level specification derived from [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md) and [`CX_PLATFORM.md`](./CX_PLATFORM.md), defining BenchKit’s own responsibilities, structure, and integration points.

It assumes the existence of external services, external tools, and real systems outside BenchKit, but describes not their internal semantics themselves, rather the responsibility boundaries and integration requirements as seen from BenchKit.
Core terminology follows the glossary in [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md).

## 2. CX基盤における位置づけ / Position Within the CX Platform

BenchKit は CX基盤の中で、実行・結果管理・ポータルの中核を担う。

BenchKit 自体の外側には、以下が存在しうる。

- GitHub / GitLab などの外部サービス
- GitLab Runner / Jacamar CI などの実行接続機構
- 実システムおよびスケジューラ
- BenchPark, Spack, Ramble などの外部ツール
- 将来の推定モデルサービス
- 将来の AI サービス

Within the CX Platform, BenchKit is the core for execution, result management, and portal functions.

Outside BenchKit itself may exist:

- external services such as GitHub and GitLab
- execution integration mechanisms such as GitLab Runner and Jacamar CI
- real systems and schedulers
- external tools such as BenchPark, Spack, and Ramble
- future estimation-model services
- future AI services

## 3. 基本方針 / Core Principles

### 3.1 shell-first

BenchKit の下層実行基盤は shell-first である。
アプリ開発者や HPC 利用者が、普段の実行運用に近い形で `build.sh` や `run.sh` を記述・理解・保守できることを重視する。

抽象化は必要であるが、Python による過度な隠蔽や依存の増加によって参入障壁を高めることは避ける。

The lower execution layer of BenchKit is shell-first.
It prioritizes allowing application developers and HPC users to write, understand, and maintain `build.sh` and `run.sh` in a style close to their normal operational practice.

Abstraction is necessary, but BenchKit avoids raising the barrier to entry through excessive Python-based concealment or dependency growth.

### 3.2 ポータル中心の利用体験（portal-first） / Portal-Centered Interaction

BenchKit の上層利用体験は、ポータル中心の利用体験を基本とする。
利用者は可能な限りスパコンへ直接ログインすることなく、
結果参照、推定確認、使用量確認、将来の条件変更申請や AI 指示を行えることを目指す。

The upper user experience of BenchKit is based on portal-centered interaction.
Users should, as much as possible, be able to inspect results, estimation outputs, usage, and future request or AI workflows without directly logging into supercomputers.

### 3.3 明示的な責務分離 / Explicit Separation of Responsibilities

BenchKit は、アプリ固有差分、システム固有差分、CI 生成、結果正規化、可視化の責務を分離する。

BenchKit separates responsibilities among application-specific differences, system-specific differences, CI generation, result normalization, and visualization.

### 3.4 ロックイン回避と差し替え可能な推定基盤 / Avoiding Lock-In and Preserving Replaceable Estimation

BenchKit は、単一の計測ツールや単一の推定方式に固定されないことを基本とする。
BenchKit 自身が担うべきなのは、特定手法を埋め込むことよりも、異なる計測方式や推定方式を受け入れ、保存し、表示し、比較できる共通契約を提供することである。

そのため BenchKit は、少なくとも概念上、以下を分離して扱えることが望ましい。

- benchmark 結果そのもの
- 推定入力となる追加計測情報
- 推定モデル識別情報
- 推定結果の標準形式

BenchKit should avoid being fixed to any single measurement tool or estimation method.
Its role is not primarily to embed one specific method, but to provide a common contract that can accept, store, present, and compare different measurement and estimation approaches.

For that reason, BenchKit should preferably be able to separate at least:

- benchmark results themselves
- additional measurement data used as estimation input
- estimation-model identification information
- the standard form of estimation results

## 4. BenchKit の主要責務 / Main Responsibilities

BenchKit は以下を責務として持つ。

- アプリごとのベンチマーク実行定義を保持すること
- system ごとの実行条件と queue 情報を参照して CI ジョブを生成すること
- `run.sh` の出力を標準化された Result JSON へ正規化すること
- 推定結果を標準化された Estimate JSON として扱うこと
- 軽量な推定経路と詳細な推定経路の両方を受け入れられること
- Web ポータルとして結果、推定、使用量を提示すること
- 将来の申請・承認・自動 PR・AI 最適化との接続点を提供すること

BenchKit is responsible for:

- holding per-application benchmark execution definitions
- generating CI jobs using system-specific execution and queue information
- normalizing `run.sh` output into standardized Result JSON
- handling estimation output as standardized Estimate JSON
- accommodating both lightweight and detailed estimation paths
- presenting results, estimation outputs, and usage through a web portal
- providing integration points for future request, approval, auto-PR, and AI optimization workflows

## 5. 非責務 / Non-Responsibilities

BenchKit は以下を単独では責務としない。

- 外部 CI サービス自身の管理
- 実システムそのものの管理
- スケジューラ自身の内部仕様
- 外部ツール自身の内部仕様
- 人間の承認を要する重要判断の代替

ただし、これらが BenchKit に無関係という意味ではない。
BenchKit は接続条件、前提条件、入力出力条件を明示的に扱う必要がある。

BenchKit is not solely responsible for:

- administering external CI services themselves
- administering real systems themselves
- the internal semantics of schedulers
- the internal semantics of external tools
- replacing critical human approvals

However, this does not mean they are irrelevant to BenchKit.
BenchKit must explicitly handle their integration conditions, assumptions, and input/output contracts.

## 6. 構成 / Structure

BenchKit は概ね以下の論理構成を持つ。

### 6.1 アプリ実装層 / Application Implementation Layer

アプリごとの実装層である。
各アプリは原則として以下を持つ。

- `build.sh`
- `run.sh`
- `list.csv`
- 必要に応じて `estimate.sh`

ここでは、ソース取得、ビルド、実行、FOM 抽出などのアプリ固有処理を定義する。

This is the per-application implementation layer.
Each application normally contains:

- `build.sh`
- `run.sh`
- `list.csv`
- optionally `estimate.sh`

This layer defines application-specific behavior such as source acquisition, build, execution, and FOM extraction.

### 6.2 共通実行基盤層 / Shared Execution Foundation

BenchKit の共通実行基盤である。
ここでは主に以下を担う。

- 共通関数
- CI ジョブ生成
- 結果正規化
- タイミング情報収集
- 送信支援

`bk_functions.sh` のような共通関数は、shell-first を維持しながら定型処理を吸収する中核である。

This is the shared execution foundation of BenchKit.
It mainly provides:

- common functions
- CI job generation
- result normalization
- timing collection
- sending support

Common shell functions such as those in `bk_functions.sh` are central to absorbing repeated patterns while preserving the shell-first approach.

### 6.3 system・queue 定義層 / System and Queue Definition Layer

BenchKit の system / queue 定義層である。

主な役割:

- `system.csv` に system 固有・拠点固有の実行設定を持つ
- `queue.csv` に scheduler template を持つ
- app 側の `list.csv` から system 固有事情を切り離す

`system.csv` は system 名、mode、runner tag、queue、queue_group などの正本である。

This is the system and queue definition layer.

Main roles:

- `system.csv` holds system-specific and site-specific execution settings
- `queue.csv` holds scheduler templates
- system-specific concerns are separated from app-side `list.csv`

`system.csv` is the source of truth for items such as system name, mode, runner tag, queue, and queue_group.

### 6.4 ポータル層 / Portal Layer

BenchKit のポータル層である。

主な役割:

- 結果一覧
- 結果詳細
- 比較表示
- 推定結果表示
- 使用量表示
- 認証・権限制御
- 将来の申請・承認ワークフローへの接続点

This is the portal layer of BenchKit.

Main roles:

- result listing
- result detail pages
- comparison views
- estimation result views
- usage views
- authentication and authorization
- future integration points for request and approval workflows

## 7. データモデルの基本 / Core Data Model

BenchKit は少なくとも以下のデータを中心に扱う。

- 実行条件
- ベンチマーク結果
- 推定結果
- 使用量情報
- ソース出自情報

BenchKit mainly handles at least the following data:

- execution conditions
- benchmark results
- estimation results
- usage information
- source provenance

### 7.1 実行条件 / Execution Conditions

実行条件は主に app 側の `list.csv` と system 側の `system.csv` により構成される。

- `list.csv`: app ごとの実験条件マトリクス
- `system.csv`: system ごとの実行ポリシー・runner・queue 情報

Execution conditions are mainly formed by app-side `list.csv` and system-side `system.csv`.

- `list.csv`: application-specific execution matrix
- `system.csv`: system-specific execution policy, runner, and queue information

### 7.2 ベンチマーク結果 / Benchmark Results

ベンチマーク結果は、`run.sh` の出力を `result.sh` により Result JSON へ正規化したものである。

結果には少なくとも以下を含みうる。

- FOM
- FOM version
- Exp
- section / overlap 情報
- pipeline timing
- source_info
- 実行環境メタデータ

Benchmark results are produced by normalizing `run.sh` output into Result JSON through `result.sh`.

They may include at least:

- FOM
- FOM version
- Exp
- section / overlap information
- pipeline timing
- source_info
- execution-environment metadata

### 7.3 ソース出自情報 / Source Provenance

BenchKit は、少なくとも最上位アプリケーションのソース出自情報を追跡できなければならない。
特に、最上位アプリケーションの commit hash は必須追跡項目とする。

これは、AI 駆動の開発・最適化において、branch 上で細かく commit が進み、
tag や公式 version が付与されない段階でも性能評価・推定・最適化ループが進行することを想定するためである。

BenchKit が最低限追跡すべき項目は以下である。

- 最上位アプリケーションの source repository
- 最上位アプリケーションの branch
- 最上位アプリケーションの commit hash
- 必要に応じて source URL
- 補助情報としての version や tag

例:
最上位アプリケーションが GitHub 上の `qws` であれば、`main` ブランチのどの commit hash から得られた結果かを追跡できなければならない。

一方で、依存パッケージやビルド環境全体の完全な provenance 追跡は、現時点では BenchKit の必須責務とはしない。
この領域は、BenchPark、Ramble、Spack などの外部ツールが本来強みを持つ領域であり、
国際協力および役割分担の観点からも、それらに委ねることを基本方針とする。

ただし、将来的に CX 基盤全体として依存関係 provenance をより広く扱う必要が生じた場合には、
BenchKit はそれら外部ツールと接続する entry point として拡張されうる。

BenchKit must be able to track source provenance for at least the top-level application.
In particular, the commit hash of the top-level application is a mandatory tracked item.

This is required because AI-driven development and optimization may advance through many commits on a branch,
even before tags or official versions are created, while benchmarking, estimation, and optimization loops are already running.

At minimum, BenchKit should track:

- the source repository of the top-level application
- the branch of the top-level application
- the commit hash of the top-level application
- the source URL when needed
- version or tag information as supporting metadata

Example:
If the top-level application is `qws` on GitHub, BenchKit must be able to trace which commit hash on the `main` branch produced the result.

By contrast, complete provenance tracking for dependency packages and the full build environment is not currently a mandatory responsibility of BenchKit.
That area is a natural strength of external tools such as BenchPark, Ramble, and Spack, and from the perspective of international collaboration and role sharing, it should generally be delegated to them.

However, if the broader CX Platform later requires wider dependency provenance support, BenchKit may be extended as an entry point for integration with those external tools.

### 7.4 推定結果 / Estimation Results

推定結果は、実測結果やモデルに基づいて生成される Estimate JSON である。
BenchKit は、軽量な推定結果と詳細な推定結果の両方を扱えることが望ましい。
また、推定方式や計測方式の違いを将来的に比較できるよう、推定結果には方式識別のための拡張余地を持たせるべきである。

Estimation results are Estimate JSON records generated from measured results and estimation models.
BenchKit should preferably be able to handle both lightweight and detailed estimation outputs.
It should also preserve room for method-identification metadata so that different measurement and estimation approaches can be compared in the future.

## 8. 実行モデル / Execution Model

BenchKit の典型的な実行フローは以下である。

1. app ごとに `programs/<code>/list.csv` が実験条件を定義する
2. `system.csv` と `queue.csv` が system 側条件を与える
3. `matrix_generate.sh` が CI ジョブを生成する
4. `build.sh` と `run.sh` が対象 system で実行される
5. `run.sh` は `bk_emit_result` などを通じて結果行を出力する
6. `result.sh` が Result JSON を生成する
7. 結果が result_server へ送られ、一覧・比較・集計される

The typical execution flow in BenchKit is:

1. `programs/<code>/list.csv` defines execution conditions for each app
2. `system.csv` and `queue.csv` provide system-side conditions
3. `matrix_generate.sh` generates CI jobs
4. `build.sh` and `run.sh` execute on the target system
5. `run.sh` emits result lines through helpers such as `bk_emit_result`
6. `result.sh` generates Result JSON
7. results are sent to result_server for listing, comparison, and aggregation

## 9. 拠点接続 / Site Integration

BenchKit は実システムを直接管理しないが、
runner、Jacamar CI、scheduler、module 環境、共有ストレージなどの実行条件を接続可能な形で定義しなければならない。

そのため、拠点接続では少なくとも以下を扱う必要がある。

- system 名
- runner tag
- build/run の実行責任主体
- queue および submit template
- job 完了判定
- stdout/stderr/結果回収方法
- module 環境
- MPI ランチャ
- 実行アカウントと予算主体

例:
`RC_GH200` では、runner tag、queue、module load、MPI 実行方法、結果回収先が定義されていて、CI からその条件で実行できなければならない。

BenchKit does not directly manage real systems, but it must define runners, Jacamar CI, scheduler behavior, module environments, shared storage, and similar execution conditions in an integrable form.

Therefore, site integration must handle at least:

- system name
- runner tag
- ownership for build/run execution
- queue and submit template
- job completion rules
- stdout/stderr/result collection method
- module environment
- MPI launcher
- execution account and budget owner

Example:
For `RC_GH200`, the runner tag, queue, module loading, MPI launch method, and result collection destination must be defined so that CI can execute under those conditions.

## 10. 将来拡張 / Future Extensions

BenchKit は将来的に以下へ拡張されうる。

- app 追加申請フォーム
- 実験条件変更申請フォーム
- 承認付き自動 PR 生成
- 推定条件変更ワークフロー
- AI 駆動最適化ワークフロー
- BenchKit から BenchPark 定義を生成する支援
- MCP サーバとしての公開

これらは BenchKit を CX基盤の中核ポータルへ発展させる方向である。

BenchKit may be extended in the future with:

- app onboarding request forms
- execution-condition change request forms
- approval-based automatic PR generation
- estimation-condition update workflows
- AI-driven optimization workflows
- support for generating BenchPark definitions from BenchKit data
- exposure as an MCP server

These extensions move BenchKit toward the role of the central portal of the CX Platform.

## 11. 利用者視点での BenchKit / BenchKit from the User Perspective

利用者にとって BenchKit は、単なる実行スクリプト集ではなく、
スパコンへ逐一ログインすることなく性能データを扱うための窓口である。

利用者は BenchKit を通じて、少なくとも以下を行えることが望ましい。

- ベンチマーク結果の確認
- 推定結果の確認
- 使用量の確認
- 小さな実験条件変更の要求
- 小さな推定条件変更の要求
- 将来的には AI への指示

From the user perspective, BenchKit is not just a collection of execution scripts.
It is the main interface for working with performance data without repeatedly logging into supercomputers.

Users should ideally be able to use BenchKit to:

- inspect benchmark results
- inspect estimation results
- inspect usage
- request small execution-condition changes
- request small estimation-condition changes
- eventually issue instructions to AI-based workflows

## 12. 関連仕様 / Related Specifications

本仕様は以下と整合する。

- [CX_FRAMEWORK.md](./CX_FRAMEWORK.md)
- [CX_PLATFORM.md](./CX_PLATFORM.md)

This specification is aligned with:

- [CX_FRAMEWORK.md](./CX_FRAMEWORK.md)
- [CX_PLATFORM.md](./CX_PLATFORM.md)
