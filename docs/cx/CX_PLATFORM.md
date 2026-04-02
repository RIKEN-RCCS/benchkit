# CX基盤仕様 / CX Platform Specification

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
  接続要件、責務境界、追跡要件など、運用や実装において満たす必要があるもの。
- 原則:
  shell-first、ポータル中心、明示的な責務分離のような設計方針。
- 将来拡張:
  申請、承認、自動 PR、AI 連携など、将来の拡張方向。

This document follows the reading conventions defined in [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md).
In particular, it is important here to distinguish:

- mandatory requirements:
  items that must be satisfied in operation or implementation, such as connection requirements, responsibility boundaries, and tracking requirements.
- principles:
  design directions such as shell-first, portal-centered interaction, and explicit separation of responsibilities.
- future extensions:
  directions such as request flows, approvals, auto-PR, and AI integrations.

## 1. 目的 / Purpose

CX基盤は、CXフレームワークを実装するための全体システムである。

それは、ソフトウェア、外部ツール、外部サービス、計算機システム、ワークフロー、運用ルールを統合し、
継続的性能工学を実践するための実運用基盤を構成する。

The CX Platform is the overall system that implements the CX Framework.

It integrates software components, external tools, external services, compute systems, workflows, and operational policies into an operational platform for continuous performance engineering.

## 1.1 文書の位置づけ / Position of This Document

本書は、[`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md) を実装する全体システムとしての CX 基盤を定義する。
本書は、構成要素、責務境界、接続要件を定義し、個別ソフトウェアの詳細仕様は下位仕様へ委ねる。

特に、BenchKit に関する詳細は [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md) に委ねる。
主要用語は [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md) の用語集に従う。

This document defines the CX Platform as the overall system that implements [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md).
It defines components, responsibility boundaries, and connection requirements, while delegating software-specific details to lower-level specifications.

In particular, BenchKit-specific details are delegated to [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md).
Core terminology follows the glossary in [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md).

## 2. 適用範囲 / Scope

CX基盤は以下を含む。

- ベンチマーク実行基盤
- 結果収集・可視化基盤
- 推定実行基盤
- 最適化支援基盤
- AI支援実行基盤
- 多拠点実行管理
- 利用者向けポータル

The CX Platform includes:

- benchmark execution infrastructure
- result collection and visualization infrastructure
- estimation execution infrastructure
- optimization support infrastructure
- AI-assisted execution infrastructure
- multi-site execution management
- user-facing portal capabilities

## 3. BenchKit の位置づけ / Position of BenchKit

BenchKit は CX基盤を構成する中核ソフトウェアの1つである。
BenchKit は主として、CX 基盤におけるベンチマーク実行、結果正規化、結果表示、および関連ワークフローへの接続点を担う。
BenchKit の詳細な責務、構成、データモデル、接続条件は [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md) に委ねる。

BenchKit is one of the core software components of the CX Platform.
BenchKit is primarily responsible for benchmark execution, result normalization, result presentation, and integration points for related workflows within the CX Platform.
Detailed responsibilities, structure, data models, and integration conditions are delegated to [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md).

## 4. CX基盤の構成要素 / Platform Components

### 4.1 内部中核コンポーネント / Core Internal Components

#### BenchKit

BenchKit は CX 基盤における中核ソフトウェアであり、詳細は [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md) に委ねる。
本書では、BenchKit を CX 基盤の主要構成要素として位置づけるにとどめる。

BenchKit is a core software component within the CX Platform, and its details are delegated to [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md).
This document only positions BenchKit as one of the major components of the CX Platform.

#### 結果ポータル / Result Portal

利用者が以下を扱うためのポータルである。

- ベンチマーク結果の参照
- 推定結果の参照
- 使用量レポートの参照
- 将来の申請・承認・AI指示ワークフローへの接続点

現状では主に `result_server` がその役割を担う。

The Result Portal provides user-facing access to:

- benchmark results
- estimation results
- usage reports
- future integration points for requests, approvals, and AI instructions

It is currently implemented mainly by `result_server`.

#### 推定レイヤ / Estimation Layer

実測データから本番規模性能や将来機性能を推定するレイヤである。

現状では BenchKit 内に一部実装されているが、
将来的には外部モデルや外部サービスとも連携しうる。

The Estimation Layer transforms measured data into production-scale and future-system estimates.

It is currently partially implemented inside BenchKit, but may later integrate with external models and services.

#### 最適化レイヤ / Optimization Layer

性能改善の提案、実施、評価を行うレイヤである。

これには以下を含みうる。
- 人手による最適化
- AI 支援による最適化
- 将来機を見据えた最適化

現時点では発展途上のレイヤである。

The Optimization Layer proposes, applies, and evaluates performance improvements.

It may include:
- human-driven optimization
- AI-assisted optimization
- future-system-oriented optimization

It is currently an emerging layer.

### 4.2 外部ツール / External Tools

外部ツールとは、CX基盤が利用するが BenchKit 自身の内部実装ではないツールを指す。

例:
- BenchPark
- Spack
- Ramble
- コンパイラツールチェイン
- スケジューラコマンド
- 性能解析ツール

ここでいう外部ツールには、BenchKit が直接規定しないが、実行結果や運用成立性に強く影響する実行時の細かな動作仕様も含まれる。
例えば、ジョブ投入方法、ジョブ完了判定、MPI ランチャの使い方、module 環境、共有ストレージ配置、標準出力やログの扱いなどである。
ただし、これらは CX 基盤にとって無関係なものではなく、拠点接続要件として明示的に把握・管理・接続されるべき対象である。

External tools are tools used by the CX Platform but not owned as part of BenchKit itself.

Examples:
- BenchPark
- Spack
- Ramble
- compiler toolchains
- scheduler commands
- performance analysis tools

External tools here also include detailed runtime behaviors that are not directly specified by BenchKit but strongly affect execution outcomes and operational viability.
Examples include job submission semantics, job completion semantics, MPI launcher behavior, module environments, shared storage layout, and stdout/log handling.
These are not irrelevant to the CX Platform; they must be explicitly captured and managed as site integration requirements.

### 4.3 外部サービス / External Services

外部サービスとは、ネットワーク越しまたは別システムとして利用するサービスを指す。

例:
- GitHub
- GitLab
- GitHub Actions
- GitLab CI
- コンテナレジストリ
- 将来の推定モデルサービス
- 将来のAIサービス

External services are networked or separately hosted services used by the platform.

Examples:
- GitHub
- GitLab
- GitHub Actions
- GitLab CI
- container registries
- future model services
- future AI services

### 4.4 実行環境 / Execution Environments

実行環境とは、実際にジョブが動作する計算機システムを指す。

例:
- Fugaku
- MiyabiG
- MiyabiC
- RC_GH200
- RC_GENOA
- 将来の実システム

実行環境は単なる計算資源ではなく、runner や Jacamar CI などの接続先として運用上の条件を伴う。
そのため、各実行環境については拠点接続の観点から、ジョブ投入方式、runner 登録方式、認証・権限、実行アカウント、利用可能ストレージ、module 環境、MPI 実行方法などを定義する必要がある。

Execution environments are the real compute systems on which workloads run.

Examples:
- Fugaku
- MiyabiG
- MiyabiC
- RC_GH200
- RC_GENOA
- future real systems

Execution environments are not just compute resources; they are operational integration targets for runners, Jacamar CI, and related components.
For each execution environment, the CX Platform must define site integration conditions such as job submission method, runner registration model, authentication and permissions, execution account, available storage, module environment, and MPI launch method.

## 5. 責務境界 / Responsibility Boundaries

### 5.1 BenchKit の責務 / BenchKit Responsibilities

BenchKit が責任を持つもの:
- ベンチマーク実行定義
- system / queue とベンチ実行の対応付け
- runner / scheduler / 実システムの接続条件の整理
- 結果ファイルの標準化
- 結果表示
- 推定ワークフローへの入口
- 使用量集計表示
- アプリ追加の受け皿

BenchKit owns:
- benchmark execution definitions
- mapping between systems/queues and benchmark workflows
- organization of runner / scheduler / real-system integration conditions
- result normalization
- result presentation
- entry points to estimation workflows
- usage accounting views
- application onboarding entry points

### 5.2 外部ツールの責務 / External Tool Responsibilities

外部ツールが責任を持つもの:
- パッケージビルドフレームワーク
- BenchKit 外部のベンチマーク定義体系
- システム固有パッケージ解決
- BenchKit が直接規定しない実行時の細かな動作仕様

ただし、外部ツールに依存する実行時仕様であっても、CX 基盤側はそれを拠点接続要件として把握し、runner 登録、Jacamar 設定、ジョブ完了判定、結果回収条件などに落とし込まなければならない。
したがって、ここでいう外部責務は「CX 基盤が考慮しなくてよい領域」を意味しない。

External tools own:
- package build frameworks
- benchmark definition semantics outside BenchKit
- system-specific package resolution
- detailed runtime behaviors not directly specified by BenchKit

However, even when runtime behavior is governed by external tools, the CX Platform must still capture it as site integration requirements and translate it into runner registration, Jacamar configuration, job completion rules, and result collection conditions.
External responsibility here does not mean the CX Platform may ignore the area.

### 5.3 外部サービスの責務 / External Service Responsibilities

外部サービスが責任を持つもの:
- リポジトリホスティング
- CI スケジューリング
- 外部認証
- 外部オーケストレーション

External services own:
- repository hosting
- CI scheduling
- externally delegated authentication
- external orchestration

### 5.4 人間の責務 / Human Responsibilities

人間が責任を持つもの:
- ベンチマーク意図の定義
- 重要変更の承認
- 最適化結果の妥当性判断
- 予算・権限・ポリシー管理
- 将来機仮定の判断

Humans remain responsible for:
- defining benchmark intent
- approving critical changes
- validating optimization outcomes
- governing budgets, permissions, and policies
- judging future-architecture assumptions

## 6. 接続要件 / Connection Requirements

CX基盤では、構成要素間の接続要件を明確に定義する必要がある。

The CX Platform must define explicit connection requirements among its components.

### 6.1 ソース・CI接続 / Source and CI Connections

- リポジトリイベントがベンチマークワークフローを起動できること
- CI フィルタにより実行範囲を制御できること
- 生成されたワークフローが監査可能であること

- Repository events must be able to trigger benchmark workflows
- CI filters must support scoped execution
- Generated workflows must remain auditable

### 6.2 計算機接続 / Compute Connections

- runner が実システムに適切に対応付くこと
- スケジューラ設定が明示的であること
- 利用アカウント、予算主体、拠点所有者が追跡可能であること
- Jacamar CI や GitLab Runner の登録条件が拠点ごとに明示されること
- ジョブ投入、待機、完了判定、失敗判定の意味が明示されること
- module 環境、MPI 実行方法、共有ストレージ前提などの実行条件が明示されること

- Runners must map cleanly to real systems
- Scheduler configuration must be explicit
- Account, budget owner, and site ownership must be traceable
- Jacamar CI and GitLab Runner registration conditions must be explicit for each site
- Job submission, waiting, completion, and failure semantics must be explicit
- Runtime conditions such as module environment, MPI launch method, and shared-storage assumptions must be explicit

### 6.2.1 拠点接続要件 / Site Integration Requirements

各拠点・各実システムについて、少なくとも以下を定義できる必要がある。

- system 名と対応する runner tag
- build 用 runner と run 用 runner の分離有無
- 使用するスケジューラと submit template
- queue および queue_group
- Jacamar executor 設定またはそれに相当する実行制御条件
- ジョブ完了判定・失敗判定の条件
- 標準出力・標準エラー・結果ファイルの回収方法
- module 環境、MPI ランチャ、必要ランタイム
- 実行アカウント、予算主体、責任主体
- データ配置および共有ストレージ前提

For each site and real system, the platform should be able to define at least:

- system name and corresponding runner tag
- whether build and run use separate runners
- scheduler and submit template
- queue and queue_group
- Jacamar executor configuration or equivalent execution-control conditions
- job completion and failure rules
- collection method for stdout, stderr, and result files
- module environment, MPI launcher, and required runtime
- execution account, budget owner, and responsible owner
- data placement and shared-storage assumptions

### 6.3 データ接続 / Data Connections

- ベンチマーク結果が安定したスキーマへ正規化されること
- 推定結果が保存・参照可能であること
- ソース、システム、ワークフローとの対応関係が追跡可能であること

- Benchmark results must be normalized into stable schemas
- Estimation results must be storable and reviewable
- Provenance must be traceable to source, system, and workflow

### 6.4 ポータル接続 / Portal Connections

- 利用者がスパコンへ直接ログインせずに結果を確認できること
- 利用者が実験条件や推定条件の微修正を要求できること
- 将来は AI への指示も制御付きで行えること

- Users must be able to inspect results without direct supercomputer login
- Users should be able to request small changes to execution and estimation conditions
- Future AI instructions should enter through controlled interfaces

## 7. 利用者視点での目標 / User-Facing Goals

利用者およびアプリ開発者にとって、CX基盤は以下を一元的に扱えるポータルとなることを目指す。

- ベンチマーク結果の参照
- 推定結果の参照
- 履歴の参照
- 実験条件の微修正要求
- 推定モデルやスケーリングモデルの微修正要求
- AI が生成した提案の確認
- 承認済みワークフローの起動

From the user and application developer perspective, the CX Platform should become the main portal where they can:

- view benchmark results
- view estimation results
- inspect historical trends
- request small execution-condition changes
- request small estimation/scaling-model changes
- review AI-generated suggestions
- trigger approved workflows

## 8. 運用目標 / Operational Goals

CX基盤は以下を支援すべきである。

- 多拠点運用
- 多アカウント・多予算主体の実行管理
- 再現性と provenance の確保
- 承認付きワークフロー変更
- 将来システムや外部サービスの段階的統合

The platform should support:

- multi-site operation
- multi-account and multi-budget execution governance
- reproducibility and provenance tracking
- approval-based workflow changes
- gradual integration of future systems and external services

## 9. アーキテクチャ方針 / Architectural Direction

長期的な方針は以下である。

- 下層は shell-first の実行基盤
- 上層は portal-first の利用体験
- 外部ツール・外部サービスとの境界を明示する
- 申請・承認・自動PR・AI連携を段階的に追加する
- BenchKit を CX基盤の中核ポータルへ発展させる

The long-term direction is:

- shell-first execution at the lower layer
- portal-first interaction at the upper layer
- explicit boundaries with external tools and services
- gradual addition of request, approval, auto-PR, and AI integrations
- evolution of BenchKit toward the core portal of the CX Platform

## 10. 下位仕様との関係 / Relationship to Lower-Level Specifications

CX基盤仕様は、以下の親仕様となる。

- BenchKit 仕様
- Result / Estimate データモデル仕様
- 申請・承認ワークフロー仕様
- 最適化ワークフロー仕様
- AI 連携仕様

The CX Platform specification is the parent specification for:

- BenchKit specifications
- Result / Estimate data model specifications
- request and approval workflow specifications
- optimization workflow specifications
- AI integration specifications
