# CXフレームワーク仕様 / CX Framework Specification

## 言語方針 / Language Policy

本書は日本語を正本とし、英語は参照用の補助訳とする。
解釈に差異がある場合は日本語版を優先する。

This document uses Japanese as the authoritative version.
The English text is provided as a supporting reference translation.
If any discrepancy exists, the Japanese version takes precedence.

## 読み方のルール / Reading Conventions

本書および下位仕様では、記述の強さを以下のように読む。

- `〜しなければならない` / `must`:
  必須要件を示す。
- `〜を基本とする` / `should generally`:
  原則的な方針を示す。
- `〜が望ましい` / `should`:
  推奨事項を示す。
- `将来的には` / `may later`:
  将来拡張や構想を示し、現時点の必須実装を意味しない。

In this document and its lower-level specifications, requirement strength should be read as follows.

- `must`:
  mandatory requirement.
- `should generally`:
  default principle or preferred baseline.
- `should`:
  recommendation.
- `may later`:
  future extension or direction, not a current mandatory implementation requirement.

## 1. 目的 / Purpose

CXフレームワークは、複数拠点・複数アプリケーション・複数世代アーキテクチャにまたがって、
性能の計測、推定、分析、最適化、高度化を継続的に回すための概念的・機能的枠組みである。

CXフレームワークは単一のソフトウェア製品ではない。
それは、基盤、ツール、サービス、ワークフロー、関係者の役割を整理するための上位フレームワークである。

The CX Framework is a conceptual and functional framework for continuously measuring, estimating, analyzing, optimizing, and advancing application performance across multiple sites, applications, and architecture generations.

The CX Framework is not a single software product.
It is a higher-level framework that organizes the roles of platforms, tools, services, workflows, and stakeholders.

## 1.1 文書の位置づけ / Position of This Document

本書は、CX 全体の最上位にある概念仕様である。
本書は「何を継続的に回すか」を定義し、個別ソフトウェアや個別サービスの実装詳細は規定しない。

下位には、少なくとも以下の仕様がぶら下がる。

- [`CX_PLATFORM.md`](./CX_PLATFORM.md): CX フレームワークを実装する全体システムの仕様
- [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md): BenchKit の責務・構成・接続点の仕様

This document is the top-level conceptual specification for CX as a whole.
It defines what should run continuously, and does not specify implementation details of individual software components or services.

At least the following lower-level specifications are expected beneath it:

- [`CX_PLATFORM.md`](./CX_PLATFORM.md): the specification of the overall system implementing the CX Framework
- [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md): the specification of BenchKit responsibilities, structure, and integration points

## 2. 適用範囲 / Scope

CXフレームワークは以下を対象とする。

- 継続的ベンチマーク（CB: Continuous Benchmarking）
- 継続的推定（CE: Continuous Estimation）
- 継続的フィードバック（CF: Continuous Feedback）
- 継続的最適化（CO: Continuous Optimization）
- 継続的高度化（CA: Continuous Advancement）

対象利用者は以下を含む。

- アプリケーション開発者
- 性能評価担当者
- HPC拠点運用者
- 調達・将来アーキテクチャ評価担当者
- AI駆動エージェント

The CX Framework covers the following:

- Continuous Benchmarking (CB)
- Continuous Estimation (CE)
- Continuous Feedback (CF)
- Continuous Optimization (CO)
- Continuous Advancement (CA)

It applies to:

- application developers
- performance engineers
- HPC site operators
- procurement and future-architecture evaluation stakeholders
- AI-driven agents

## 2.1 用語集 / Glossary

本仕様および下位仕様では、主要用語を以下の意味で用いる。

- `CB`:
  継続的ベンチマーク。複数アプリケーション・複数システムに対して、ベンチマーク実行と性能検証を継続的に行うこと。
- `CE`:
  継続的推定。実測結果に基づき、本番規模性能、スケーリング挙動、将来アーキテクチャでの性能を継続的に推定すること。
- `CF`:
  継続的フィードバック。計測結果、推定結果、最適化結果を継続的に人間およびシステムへ返すこと。
- `CO`:
  継続的最適化。個別アプリケーションや個別ワークロードに対して、コード、設定、ワークフローを改善し性能を高めること。
- `CA`:
  継続的高度化。個別アプリケーションの最適化ではなく、CX 基盤全体、モデル、ワークフロー、ポータル、AI 連携、運用方式を継続的にエンハンスすること。
- `拠点接続`:
  実システム、runner、Jacamar CI、scheduler、module 環境、共有ストレージ、実行アカウント、結果回収条件などを、CX 基盤や BenchKit から接続可能な形で定義・管理すること。
- `ソース出自情報`:
  実行結果や推定結果が、どのソースコード状態に由来するかを追跡するための情報。少なくとも最上位アプリケーションの source repository、branch、commit hash を含みうる。
- `最上位アプリケーション`:
  CX 基盤が直接対象とするベンチマーク対象アプリケーション本体。依存パッケージや依存ライブラリではなく、性能結果や最適化結果を第一義的に結び付ける主体を指す。

In this specification and its lower-level specifications, the following terms are used with the meanings below.

- `CB`:
  Continuous Benchmarking. The continuous execution of benchmark and performance validation workloads across multiple applications and systems.
- `CE`:
  Continuous Estimation. The continuous estimation of production-scale performance, scaling behavior, and future-architecture performance from measured results.
- `CF`:
  Continuous Feedback. The continuous return of measured, estimated, and optimization-related information back to humans and systems.
- `CO`:
  Continuous Optimization. The continuous improvement of code, configuration, and workflow for individual applications or workloads.
- `CA`:
  Continuous Advancement. Not the optimization of a single application, but the continuous enhancement of the CX Platform as a whole, including models, workflows, portal capabilities, AI integration, and operating methods.
- `site integration`:
  The definition and management of real systems, runners, Jacamar CI, scheduler behavior, module environments, shared storage, execution accounts, and result-collection conditions in a form that can be integrated with the CX Platform and BenchKit.
- `source provenance`:
  Information used to trace which source-code state produced a benchmark or estimation result. At minimum, it may include the source repository, branch, and commit hash of the top-level application.
- `top-level application`:
  The benchmark target application directly handled by the CX Platform. It does not mean dependency packages or libraries, but the primary subject to which performance and optimization results are attached.

## 3. 中核概念 / Core Concepts

### 3.1 継続的ベンチマーク（CB） / Continuous Benchmarking

継続的ベンチマークとは、複数のアプリケーションと複数のシステムに対して、
ベンチマーク実行と性能検証を継続的に行う活動である。

目的:
- 性能劣化の検知
- ベンチマーク結果の継続蓄積
- システム間・版間比較
- ベンチマーク運用状態の可視化

入力:
- ベンチマーク定義
- 実行条件
- システム定義
- ソースコードまたはバイナリ

出力:
- ベンチマーク結果
- 性能解析データ
- 実行メタデータ
- 履歴データ

Continuous Benchmarking is the continuous execution of benchmark and performance validation workloads across multiple applications and systems.

Goals:
- detect regressions
- accumulate benchmark history
- compare systems and software versions
- maintain operational visibility

Inputs:
- benchmark definitions
- execution conditions
- system definitions
- source code or binary artifacts

Outputs:
- benchmark result records
- performance analysis artifacts
- execution metadata
- historical trend data

### 3.2 継続的推定（CE） / Continuous Estimation

継続的推定とは、実測データに基づいて、
本番規模の性能指標、スケーリング挙動、将来アーキテクチャでの性能を継続的に推定する活動である。

目的:
- 小規模実験から本番規模FOMを推定する
- 将来アーキテクチャでの性能を推定する
- スケーリング挙動を外挿する
- 推定モデルを継続的に改善する

入力:
- ベンチマーク結果
- スケーリングモデル
- アーキテクチャ仮定
- システムメタデータ
- 推定条件

出力:
- 推定FOM
- スケーリング予測
- 仮定・信頼度情報
- 推定履歴

Continuous Estimation is the continuous estimation of production-scale performance, scaling behavior, and future-architecture performance from measured benchmark data.

Goals:
- infer production-level FOM from smaller tests
- estimate performance on future architectures
- support scaling extrapolation
- continuously improve estimation models

Inputs:
- benchmark result data
- scaling models
- architectural assumptions
- system metadata
- estimation conditions

Outputs:
- estimated FOM
- scaling projections
- assumptions and confidence information
- estimation histories

### 3.3 継続的フィードバック（CF） / Continuous Feedback

継続的フィードバックとは、
計測結果・推定結果・最適化結果を継続的に人間およびシステムへ返す活動である。

目的:
- 状況把握の迅速化
- 意思決定支援
- 計測と改善のループ形成

入力:
- ベンチマーク結果
- 推定結果
- 最適化結果
- 運用メタデータ

出力:
- ダッシュボード
- アラート
- レポート
- コメント
- 意思決定支援情報

Continuous Feedback is the continuous return of measured, estimated, and optimization-related performance information back to humans and systems.

Goals:
- improve visibility
- support decision making
- close the loop between measurement and action

Inputs:
- benchmark results
- estimation results
- optimization results
- operational metadata

Outputs:
- dashboards
- alerts
- reports
- comments
- decision support information

### 3.4 継続的最適化（CO） / Continuous Optimization

継続的最適化とは、
コード、設定、ワークフローの変更を通じてアプリケーション性能を継続的に改善する活動である。

目的:
- 現行システムでの実測性能改善
- 性能回帰の抑止
- 反復的チューニング作業の自動化
- AIによる最適化支援

入力:
- ソースコード
- ベンチマーク結果
- 推定結果
- 最適化指示
- システム制約

出力:
- 最適化されたコードまたは設定
- 最適化提案
- 改善実績
- 最適化履歴

Continuous Optimization is the continuous improvement of application performance through changes to code, configuration, and workflow.

Goals:
- improve measured performance on current systems
- prevent regressions
- automate repetitive tuning work
- support AI-assisted optimization

Inputs:
- source code
- benchmark results
- estimation results
- optimization directives
- system constraints

Outputs:
- optimized code or configuration
- optimization suggestions
- measured improvement records
- optimization history

### 3.5 継続的高度化（CA） / Continuous Advancement

継続的高度化とは、
個別アプリケーションの性能改善そのものではなく、CX全体を支える基盤、モデル、ワークフロー、ポータル、運用方式、AI連携方式を継続的に高度化する活動である。

言い換えると、CA は **CX 全体を継続的にエンハンスするループ** である。

目的:
- CX基盤そのものの能力向上
- 推定モデル、スケーリングモデル、最適化モデルの改良
- BenchKit や周辺ポータル機能の高度化
- AI・外部ツール・外部サービスとの連携方式の改善
- 将来アーキテクチャ評価や調達支援の仕組み強化

入力:
- ベンチマーク結果
- 推定結果
- 最適化結果
- 利用者からのフィードバック
- 運用上の課題
- 将来アーキテクチャ仮定
- 技術ロードマップ

出力:
- 改良された CX基盤
- 改良されたモデル
- 改良されたワークフロー
- 改良されたポータル機能
- 改良された AI 連携・自動化機能

Continuous Advancement is not the direct optimization of a single application.
It is the continuous improvement of the platform, models, workflows, portal, operational methods, and AI integration methods that support the CX ecosystem as a whole.

In other words, CA is the loop that **continuously enhances the entire CX system**.

Goals:
- improve the capabilities of the CX Platform itself
- refine estimation, scaling, and optimization models
- enhance BenchKit and surrounding portal functionality
- improve integration with AI, external tools, and external services
- strengthen support for future-architecture evaluation and procurement

Inputs:
- benchmark results
- estimation results
- optimization results
- user feedback
- operational issues
- future architecture assumptions
- technical roadmaps

Outputs:
- improved CX Platform
- improved models
- improved workflows
- improved portal capabilities
- improved AI integration and automation

## 4. 設計原則 / Design Principles

### 4.1 ロックイン回避と差し替え可能性 / Avoiding Lock-In and Preserving Replaceability

CX フレームワークは、単一の計測ツール、単一の推定モデル、単一の最適化系、単一の外部サービスに過度に依存しないことを基本とする。
計測方法、アノテーション方式、性能カウンター採取方式、推定方式、AI 連携方式は、状況に応じて差し替え可能であることが望ましい。

この原則の目的は以下である。
- 特定ツールへのロックインを避ける
- 国際協力や外部ツール連携をしやすくする
- アプリ準備状況や拠点制約に応じて最小経路とより詳細な方法を使い分ける
- PoC 段階の手法を本番設計に持ち込みやすくする
- ある手法が陳腐化したときに別手法へ移行しやすくする

The CX Framework should avoid excessive dependence on any single measurement tool, estimation model, optimization stack, or external service.
Measurement methods, annotation styles, counter collection methods, estimation methods, and AI integration methods should be replaceable according to the situation.

The purposes of this principle are:
- to avoid lock-in to specific tools
- to make international collaboration and external-tool integration easier
- to allow a minimum path and more detailed methods to coexist according to application readiness and site constraints
- to allow PoC-stage methods to be introduced incrementally into production design
- to make migration easier when a given method becomes obsolete

## 5. 機能間の関係 / Functional Relationships

CXのサイクルは線形ではなく反復的である。

典型的な流れ:
1. CB が現状性能を計測する
2. CE が本番規模や将来機性能を推定する
3. CF が結果を可視化・共有する
4. CO がコード・設定・ワークフローを改善する
5. CA が CX基盤やモデルや運用方式そのものを強化する
6. 新たな CB により改善結果を検証する

The CX cycle is iterative rather than linear.

Typical loop:
1. CB measures current behavior.
2. CE estimates production-scale and future-system behavior.
3. CF exposes the results.
4. CO improves code, configuration, or workflow.
5. CA enhances the CX Platform, models, and operating methods themselves.
6. New CB runs validate the changes.

## 6. 利用者と役割 / Actors and Roles

### 6.1 アプリケーション開発者 / Application Developer
- ベンチマークを実行・比較したい
- 推定結果を確認したい
- 最適化や条件変更を指示したい

### 6.2 拠点運用者 / Platform Operator
- runner、権限、予算、拠点設定を管理する
- 実行状態と運用状態を監視する

### 6.3 性能評価担当者 / Performance Engineer
- FOM や推定ロジックを定義する
- 傾向やボトルネックを分析する

### 6.4 AIエージェント / AI Agent
- 最適化提案、コード修正、異常診断、ワークフロー生成を支援する
- 承認ポリシーの下で動作する

### 6.5 調達・将来機評価担当者 / Procurement and Future-Architecture Stakeholder
- 将来機評価や適合性判断に CE/CA の結果を利用する

## 7. 必須能力 / Required Capabilities

CXフレームワークを実装する基盤は、少なくとも以下を支援する必要がある。

- 多拠点実行
- 多アプリ実行
- 繰り返し可能なベンチマーク定義
- 結果の標準化
- 推定ワークフロー
- 履歴保持
- 可視化とフィードバック
- 最適化ワークフロー
- 承認付き自動化
- 将来システム評価支援
- 差し替え可能な計測方式および推定方式
- 最小経路とより詳細な推定経路の共存

A platform implementing the CX Framework should support at least:

- multi-site execution
- multi-application execution
- repeatable benchmark definitions
- result normalization
- estimation workflows
- historical retention
- visualization and feedback
- optimization workflows
- approval-based automation
- future-system evaluation support
- replaceable measurement and estimation methods
- coexistence of minimum and more detailed estimation paths

## 8. 非目標 / Non-Goals

CXフレームワークは以下を要求しない。

- 単一の実装言語
- 単一のCIシステム
- 単一のベンチマークフレームワーク
- 単一のAIツール
- 人間の承認なしの完全自律運転
- 単一の必須計測ツールチェインまたは推定ツールチェイン

The CX Framework does not require:

- a single implementation language
- a single CI system
- a single benchmarking framework
- a single AI tool
- fully autonomous execution without human approval
- a single mandatory measurement or estimation toolchain

## 9. CX基盤およびBenchKitとの関係 / Relationship to CX Platform and BenchKit

- CXフレームワークは上位の概念・機能モデルを定義する
- CX基盤はそのモデルを実装する全体システムである
- BenchKit は CX基盤を構成する中核ソフトウェアの1つである

- The CX Framework defines the conceptual and functional model.
- The CX Platform is the overall system implementing that model.
- BenchKit is one of the core software components within the CX Platform.
