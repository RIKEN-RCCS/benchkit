# 性能推定仕様 / Estimation Specification

## 言語方針 / Language Policy

本書は日本語を正本とし、英語は参照用の補助訳とする。
解釈に差異がある場合は日本語版を優先する。

This document uses Japanese as the authoritative version.
The English text is provided as a supporting reference translation.
If any discrepancy exists, the Japanese version takes precedence.

## 読み方のルール / Reading Conventions

本書は [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md) の読み方のルールに従う。

- `must`: 必須要件
- `should generally`: 基本原則
- `should`: 推奨
- `may later`: 将来拡張

This document follows the reading conventions defined in [`CX_FRAMEWORK.md`](./CX_FRAMEWORK.md).

## 1. 文書の位置づけ / Position of This Document

本書は [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md) のうち性能推定機能を詳細化する下位仕様である。
本書は、推定手法の内部アルゴリズムそのものを固定する文書ではなく、BenchKit が推定機能を受け入れ、実行し、保存し、表示するための共通ルールを定義する。

This document is a lower-level specification that details the estimation function described in [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md).
It does not fix a single estimation algorithm. Instead, it defines the common rules by which BenchKit accepts, runs, stores, and presents estimation functions.

## 2. 目的 / Purpose

BenchKit の性能推定機能は、ベンチマーク結果から以下を推定できるようにすることを目的とする。

- 本番規模 FOM
- 異なるノード数でのスケーリング挙動
- 将来アーキテクチャでの予測性能
- 区間別の時間やボトルネックの変化

同時に、性能推定機能は以下を満たさなければならない。

- 計測方法や推定方法が差し替え可能であること
- 軽量な簡易推定と詳細推定が共存できること
- アプリ側の準備状況に応じて段階導入できること
- 推定結果の前提、根拠、比較元が追跡可能であること
- 推定に必要な入力が不足している場合の扱いを明示できること

The purpose of BenchKit estimation is to make it possible to estimate:

- production-scale FOM
- scaling behavior at different node counts
- predicted performance on future architectures
- changes in section-level timing and bottlenecks

At the same time, the estimation function must satisfy the following:

- measurement and estimation methods must be replaceable
- lightweight and detailed estimation must coexist
- adoption must be possible in stages according to application readiness
- assumptions, evidence, and comparison baselines must be traceable
- the handling of missing required inputs must be explicit

## 3. 基本原則 / Core Principles

### 3.1 手法差し替え可能性 / Method Replaceability

BenchKit は、単一の性能カウンター採取方法、単一のアノテーション方式、単一の推定ツール、単一の推定モデルにロックインしてはならない。

推定処理は、少なくとも概念上、以下を分離して扱えるべきである。

- 計測入力の取得方法
- ベンチマーク結果の前処理方法
- 推定モデル
- 推定結果の出力形式

BenchKit must not be locked into a single counter collection method, annotation scheme, estimation tool, or estimation model.

At least conceptually, the estimation flow should separate:

- how measurement inputs are obtained
- how benchmark results are preprocessed
- the estimation model
- the output representation of estimation results

### 3.2 段階導入 / Staged Adoption

性能推定は、常に詳細性能カウンターや詳細アノテーションを前提としてはならない。
少なくとも以下の段階が共存できることを基本とする。

- 簡易推定:
  FOM、ノード数、既知の比較基準など少数の情報から行う推定
- 詳細推定:
  アプリ自前の区間時間、外部ツール由来の区間時間、詳細性能カウンターなどを使う推定

Estimation should not always assume detailed counters or detailed annotations.
At minimum, the following stages should be able to coexist:

- lightweight estimation:
  estimation from a small number of inputs such as FOM, node count, and known comparison baselines
- detailed estimation:
  estimation using application-defined interval timings, tool-derived interval timings, or detailed counters

### 3.2.1 詳細推定の取得方式差異 / Different Acquisition Paths Within Detailed Estimation

詳細推定は単一の方式として扱うべきではない。
少なくとも、以下の取得方式の違いを区別できることが望ましい。

- `instrumented_app_sections`
  - アプリ自前で出力された区間時間や区間別結果に基づく推定
- `instrumented_tool_sections`
  - Caliper などの外部ツール由来の区間時間や区間別結果に基づく推定
- `counter_based`
  - 特定区間に対して詳細性能カウンターが採取されていることを前提とする推定

Detailed estimation should not be treated as a single undifferentiated method.
At minimum, it should be possible to distinguish the following acquisition paths:

- `instrumented_app_sections`
  - estimation based on interval timings or section-wise results emitted by the application itself
- `instrumented_tool_sections`
  - estimation based on interval timings or section-wise results collected by external tools such as Caliper
- `counter_based`
  - estimation that assumes detailed counters are available for specific sections

### 3.3 追跡可能性 / Traceability

推定結果は、少なくとも以下を追跡できなければならない。

- どの benchmark result を入力にしたか
- どの比較基準を使ったか
- どの推定方式を使ったか
- どの仮定を置いたか

An estimation result must be traceable at least to:

- which benchmark result was used as input
- which comparison baseline was used
- which estimation method was applied
- which assumptions were made

### 3.4 適用可能性判定 / Applicability Evaluation

推定方式ごとに、必要な入力の集合を定義できなければならない。
BenchKit は、指定された推定方式に対して入力が十分かどうかを判定できることを基本とする。

必要入力が不足する場合、BenchKit または推定方式は、少なくとも以下のいずれかを明示しなければならない。

- 不適用として終了する
- 軽量な別方式へフォールバックする
- 再計測または追加準備が必要であることを返す

不足したまま成功扱いの推定結果を返してはならない。

Each estimation method must be able to define its required input set.
BenchKit should be able to judge whether the inputs are sufficient for a requested estimation method.

When required inputs are missing, BenchKit or the estimation method must explicitly do at least one of the following:

- terminate as not applicable
- fall back to a lighter-weight method
- return that re-measurement or additional preparation is required

It must not return a successful estimate while silently ignoring missing required inputs.

### 3.5 BenchKit と推定パッケージ開発者の責務境界 / Boundary Between BenchKit and Package Developers

BenchKit は、推定機構について共通ルール、識別情報、入出力、適用可能性判定結果、保存形式、比較可能性を扱う。
一方で、各推定パッケージの開発者は、少なくとも以下を定義できるものとして扱う。

- 具体的な推定アルゴリズム
- 具体的な必要入力と不足時条件
- section 名や overlap の解釈規約
- 区間ごとの推定部品の合成方法
- 補助アーティファクトの内部フォーマット
- ツール固有・ベンダー固有の呼び出し方法

したがって、本書で未定義のまま残す項目は、原則として package 開発者または外部ツール側へ委ねられる。

BenchKit handles the common rules, identifiers, inputs/outputs, applicability results, storage format, and comparability of estimation.
By contrast, each estimation-package developer is expected to define at least:

- the concrete estimation algorithm
- the concrete required inputs and missing-input conditions
- the interpretation rules for section names and overlaps
- how section-wise estimation components are composed
- the internal format of auxiliary artifacts
- tool-specific or vendor-specific invocation methods

Accordingly, items intentionally left undefined in this document are, in principle, delegated to package developers or external tools.

## 4. 推定機能の構成 / Components of the Estimation Function

性能推定機能は、概念上、以下の構成要素からなる。

1. 推定入力
2. 計測メタデータ
3. 推定モデル
4. 比較基準
5. 適用可能性判定
6. 推定結果
7. 履歴と再推定

Conceptually, the estimation function consists of:

1. estimation input
2. measurement metadata
3. estimation model
4. comparison baseline
5. applicability evaluation
6. estimation output
7. history and re-estimation

### 4.1 推定入力 / Estimation Input

推定入力は、最低限、Result JSON を起点とする。
将来的には、追加の性能カウンター、アノテーション区間時間、外部ファイル、外部サービスの結果を補助入力として使ってもよい。

また、推定対象となる `current_system` と `future_system` の両方について、推定の基準となる benchmark result を持てることを基本とする。
これらの benchmark result は、原則として少ノードで実行された実測結果であることが望ましい。
特に `future_system` 側の benchmark result は、将来システムそのものの実測でなくてもよいが、少なくとも将来システムに近い現行アーキテクチャ上で得られた実測結果、あるいはそれと同等の比較基準を持つことが望ましい。

Result JSON is the minimum required input.
In the future, additional counters, annotated interval timings, external files, or external service outputs may be used as auxiliary inputs.

In addition, both `current_system` and `future_system` should in principle have benchmark results that serve as their estimation baselines.
These benchmark results are preferably measured results obtained at small node counts.
In particular, the benchmark result on the `future_system` side does not have to be a direct measurement on the future system itself, but should preferably be at least a measured result obtained on a current architecture close to the future system, or an equivalent comparison baseline.

### 4.2 計測メタデータ / Measurement Metadata

推定に使う計測入力については、少なくとも以下を識別できることが望ましい。

- どのツールで採取したか
- どの方式で採取したか
- 軽量採取か詳細採取か
- アノテーションの有無
- 区間時間が実測か推定か
- 区間ごとにどの推定部品を適用するか
- 区間ごとにどの補助データを参照するか

For measurement inputs used by estimation, it should be possible to identify at least:

- which tool collected them
- which method was used
- whether the collection was lightweight or detailed
- whether annotations were used
- whether interval times were measured or inferred
- which estimation component is applied to each section
- which auxiliary data is referenced by each section

### 4.3 推定モデル / Estimation Model

推定モデルは、BenchKit に埋め込まれた単一モデルである必要はない。
アプリ固有スクリプト、共通 shell ライブラリ、外部ツール、外部サービスのいずれでもよい。

BenchKit における実装単位としては、これらを単独のモデルとして扱うだけでなく、計測前提や適用可能性判定を含む推定パッケージとして束ねて扱ってもよい。

ただし BenchKit から見て、少なくとも以下を識別可能にすべきである。

- モデル種別
- モデル名
- モデル版
- スケーリング方式
- 将来システム仮定

The estimation model need not be a single built-in BenchKit model.
It may be an application-specific script, a shared shell library, an external tool, or an external service.

As an implementation unit in BenchKit, these may be handled not only as standalone models but also as estimation packages that bundle measurement assumptions and applicability evaluation.

However, from the perspective of BenchKit, the following should be identifiable:

- model type
- model name
- model version
- scaling method
- future-system assumption

また、推定モデルは常に単一モデルである必要はない。
区間ごとに異なる推定方式を組み合わせる複合推定を許容すべきである。
特に、計算区間、通信区間、入出力区間などに対して、異なる入力種別や推定方式を適用できることが望ましい。

The estimation model need not always be a single monolithic model.
Composite estimation that combines different estimation methods for different sections should be allowed.
In particular, it is desirable to apply different input types or estimation methods to compute, communication, and I/O sections.

さらに、BenchKit は少なくとも次の二種類の推定モデルを区別して扱えることが望ましい。

- `intra_system_scaling_model`
  - 少ノード benchmark result から、同種または同一系統のシステム上の target nodes へ伸長する推定モデル
- `cross_system_projection_model`
  - 別系統または別アーキテクチャの benchmark result から、対象システム上の target へ投影する推定モデル

ここで重要なのは、`current_system` 側の推定が必ずしも `intra_system_scaling_model` に限られないことである。
たとえば、別の現行システムからの写像が有効であれば、`current_system` 側の多ノード推定にも `cross_system_projection_model` を使ってよい。

これらは同一の推定モデルであってもよいが、別個のモデル、別個の推定パッケージ、あるいは複合推定パッケージ内の別部品として扱ってよい。

In addition, BenchKit should preferably be able to distinguish at least the following two kinds of estimation models:

- `intra_system_scaling_model`
  - a model that scales a small-node benchmark result to target nodes on the same or closely related system line
- `cross_system_projection_model`
  - a model that projects from a benchmark result on a different system line or architecture to the target system

The important point is that estimation on the `current_system` side is not necessarily limited to `intra_system_scaling_model`.
For example, if projection from another current system is valid, `cross_system_projection_model` may also be used for multi-node estimation on the `current_system` side.

These may be the same model, separate models, separate estimation packages, or separate components within a composite estimation package.

さらに、これらのモデル種別は単なる分類名ではなく、入力 benchmark result の `system` と、推定出力側の対象 `system` との整合条件を持たなければならない。

- `intra_system_scaling_model`
  - 入力 benchmark result の `system` と推定出力側の対象 `system` が一致するか、少なくとも同一系統であることを前提とする
- `cross_system_projection_model`
  - 入力 benchmark result の `system` は推定元システムを表し、推定出力側の対象 `system` は推定先システムを表す
  - 両者は一致しなくてよいが、推定元と推定先の向きが明示されていなければならない

In addition, these model kinds must not be treated as mere labels; they must carry consistency conditions between the input benchmark-result `system` and the output-side target `system`.

- `intra_system_scaling_model`
  - assumes that the input benchmark-result `system` and the output-side target `system` are the same, or at least belong to the same system line
- `cross_system_projection_model`
  - treats the input benchmark-result `system` as the source system and the output-side target `system` as the destination system
  - they need not match, but the source-to-target direction must be explicit

### 4.3.1 区間メタデータ / Section Metadata

section は単なる時間値ではなく、必要に応じて当該区間に適用する推定部品と、その推定に必要な補助データ参照を保持できることが望ましい。
少なくとも以下を保持してよい。

- section 名
- 区間時間
- 区間に適用する推定パッケージ名
- 補助データ参照

これにより、アプリ開発者は区間ごとに推定方式を差し替えやすくなり、推定パッケージ開発者は区間ごとの必要入力に集中しやすくなる。

A section should be able to hold not only a time value, but also the estimation component applied to that section and references to auxiliary data required by that estimation.
At minimum, the following may be retained:

- section name
- section time
- estimation package name applied to the section
- auxiliary data references

This makes it easier for application developers to switch estimation methods section by section, and for package developers to focus on section-wise required inputs.

### 4.4 比較基準 / Comparison Baseline

推定では、比較基準となる benchmark result が重要である。
比較基準は、少なくとも以下のいずれかで指定できるべきである。

- 明示的な uuid
- code、system、Exp などの条件による検索
- 外部サービスから取得される基準

In estimation, baseline benchmark results are important.
The baseline should be specifiable at least by one of:

- explicit uuid
- a query by conditions such as code, system, and Exp
- a baseline obtained from an external service

### 4.4.1 ターゲットノード数とスケーリング前提 / Target Node Count and Scaling Assumption

`current_system` と `future_system` の両方について、推定先のターゲットノード数を明示できなければならない。
このターゲットノード数は、少なくとも初期段階では app 側または app 連携層が決定できることを基本とする。

推定の基本前提は、原則としてウィークスケーリングである。
すなわち、基準 benchmark result が少ノードで測定されたものであっても、推定時には対象システムごとのターゲットノード数へ問題サイズを増やしながら性能を外挿する前提を基本とする。
このとき、追加の補正を導入しない限り、FOM はターゲットノード数によらず一定とみなすのが基本である。

For both `current_system` and `future_system`, the target node count of the estimate must be expressible.
At least at the initial stage, this target node count is expected to be chosen by the application side or the application integration layer.

The default scaling assumption is, in principle, weak scaling.
That is, even when the baseline benchmark result is measured at a small node count, the estimate is fundamentally expected to extrapolate performance toward the target node count on each system while increasing problem size.
Unless additional correction terms are introduced, the basic interpretation is that FOM remains constant regardless of the target node count.

ただし、`current_system` 側と `future_system` 側で同一のスケーリング規則を強制する必要はない。
また、`current_system` 側が必ずしも system 内スケーリングである必要もない。
`intra_system_scaling_model` を使う場合には「基本は FOM 一定で、一部区間のみ補正する」という扱いが自然である一方、`cross_system_projection_model` を使う場合には CPU/GPU 演算性能、通信性能、メモリ性能などに応じて区間時間そのものを変える投影モデルが自然である。

However, the same scaling rule need not be forced on both the `current_system` side and the `future_system` side.
Also, the `current_system` side need not always be an intra-system scaling case.
When using `intra_system_scaling_model`, a rule such as "FOM is constant by default, with selective corrections only for some sections" is natural, whereas when using `cross_system_projection_model`, a projection model that changes section timings themselves according to CPU/GPU performance, communication performance, or memory performance is natural.

したがって、BenchKit は少なくとも次を検証できることが望ましい。

- `intra_system_scaling_model` が指定されたとき、入力 benchmark result の `system` と推定出力側の対象 `system` が一致または同一系統であること
- `cross_system_projection_model` が指定されたとき、入力 benchmark result の `system` が推定元、推定出力側の対象 `system` が推定先として解釈できること

Accordingly, BenchKit should preferably be able to validate at least the following:

- when `intra_system_scaling_model` is specified, the input benchmark-result `system` and the output-side target `system` are the same or from the same system line
- when `cross_system_projection_model` is specified, the input benchmark-result `system` can be interpreted as the source system and the output-side target `system` as the destination system

### 4.4.2 通信成分補正の前提 / Preconditions for Communication-Cost Adjustment

集団通信時間や全ノード同期処理オーバーヘッドなどの通信成分に対する補正は、少なくともそれらの成分が別途分離されている場合に限って扱うべきである。
section 分解、overlap、通信区間時間、またはそれに準ずる情報が無い軽量推定では、通信成分補正や同期オーバーヘッド補正を前提としてはならない。

この種の補正を適用する場合は、Estimate JSON の `assumptions` または `model` に明示されなければならない。

Adjustments for communication components such as collective communication time or all-node synchronization overhead should only be used when those components are separately identified.
Lightweight estimation without section breakdown, overlap, communication interval timing, or equivalent information must not assume communication-cost or synchronization-overhead adjustment.

When this kind of adjustment is applied, it must be made explicit in `assumptions` or `model` in Estimate JSON.

また、特定区間の推定方式は、他の区間とは独立に切り替え可能であることが望ましい。
たとえば、ある区間はカウンターベース、別の区間はトレースベース、さらに別の区間は区間時間ベースという組合せを許容すべきである。

In addition, the estimation method for a particular section should preferably be switchable independently from that of other sections.
For example, the framework should allow combinations such as counter-based estimation for one section, trace-based estimation for another, and interval-timing-based estimation for others.

### 4.4.3 overlap 区間 / Overlap Sections

overlap は、少なくとも二つ以上の section が同時進行しうる区間を表すものとして扱う。
overlap 自体も、section と同様に推定対象となる区間の一種であり、必要に応じて独立した区間推定部品で扱ってよい。

初期段階では、overlap の実際の推定方法は手法依存としてよい。
もっとも単純な参照手法としては、関連する section の時間から `max(section_A, section_B, ...)` を用いる近似を許容してよい。
より詳細な方式では、overlap 区間自体に対する独立したモデル、トレース、カウンター、区間時間を用いてよい。

Overlap should be treated as representing a region in which at least two or more sections may progress simultaneously.
Overlap itself is also a kind of estimable region, just like a section, and may be handled by an independent section-estimation component when needed.

At the initial stage, the actual estimation method for overlap may be method-dependent.
As the simplest reference method, an approximation based on `max(section_A, section_B, ...)` may be allowed.
More detailed methods may instead use an explicit model, trace, counters, or interval timings for the overlap region itself.

### 4.5 適用可能性判定 / Applicability Evaluation

推定実行前に、対象方式が必要とする入力が揃っているかを判定できることが望ましい。
この判定は、少なくとも以下を返せることが望ましい。

- 適用可能
- フォールバック適用可能
- 不適用
- 再計測または追加準備が必要

BenchKit should preferably be able to evaluate whether the required inputs for a chosen estimation method are present before execution.
This evaluation should preferably be able to return at least:

- applicable
- applicable with fallback
- not applicable
- re-measurement or additional preparation required

### 4.6 履歴と再推定 / History and Re-Estimation

推定は一度きりの計算ではなく、モデルや仮定の更新に応じて再推定できることが重要である。
BenchKit は、少なくとも以下を扱えるべきである。

- benchmark result を再指定しての再推定
- 推定結果の履歴保持
- 異なる推定方式の比較

Estimation is not a one-time calculation. Re-estimation in response to updated models or assumptions is important.
BenchKit should be able to handle at least:

- re-estimation from a specified benchmark result
- history retention of estimation results
- comparison of different estimation methods

## 5. 推定方式の分類 / Classes of Estimation Methods

BenchKit は少なくとも、以下の推定方式を受け入れられることが望ましい。

### 5.1 簡易推定 / Lightweight Estimation

入力:

- FOM
- ノード数
- 比較基準
- 既知の倍率や単純モデル
- 各システム側のターゲットノード数

用途:

- 高頻度実行
- PoC
- 準備が進んでいない app

### 5.2 詳細推定 / Detailed Estimation

入力:

- アプリ自前の区間時間や区間別結果
- 外部ツール由来の区間時間や区間別結果
- 詳細性能カウンター
- 区間ごとの方式切替情報
- より複雑なモデルや外部モデル
- 各システム側のターゲットノード数

用途:

- 深い分析
- 将来機評価
- AI 駆動最適化の高精度評価

BenchKit should preferably support at least the following estimation classes:

### 5.1 Lightweight Estimation

Inputs:

- FOM
- node count
- baseline result
- known scaling ratio or simple model
- target node count for each system

Typical use:

- high-frequency execution
- PoC
- applications not yet fully prepared

基本形では、ターゲットノード数が変わっても FOM は一定とみなす。
追加補正を入れる場合は、軽量推定の基本形ではなく、補正付き軽量推定またはより詳細な推定方式として扱うべきである。

In the basic form, FOM is treated as constant even when the target node count changes.
If additional correction terms are introduced, they should be treated not as the default lightweight estimation, but as a corrected lightweight method or a more detailed estimation method.

### 5.2 Detailed Estimation

Inputs:

- application-defined interval timings or section-wise results
- tool-derived interval timings or section-wise results
- detailed performance counters
- section-wise method-selection information
- more complex or external models
- target node count for each system

Typical use:

- deeper analysis
- future-system evaluation
- higher-fidelity evaluation for AI-driven optimization

## 6. BenchKit における推定実装要件 / BenchKit-Side Requirements

BenchKit は、推定機能について少なくとも以下を満たすべきである。

1. app ごとの推定処理を呼び出せること
2. Result JSON を推定入力として受け渡せること
3. Estimate JSON を標準形式で保存できること
4. 再推定を起動できること
5. 推定結果を一覧・詳細で表示できること
6. 推定方式の違いを将来的に比較可能な形で保持できること

BenchKit should satisfy at least the following:

1. it should be able to invoke per-application estimation logic
2. it should pass Result JSON as estimation input
3. it should store Estimate JSON in a standard format
4. it should support re-estimation
5. it should present estimation results in list and detail views
6. it should preserve enough metadata to compare estimation methods in the future
7. it should make missing-input handling explicit rather than implicit

## 7. 現時点で未確定の事項 / Items Intentionally Left Open

以下は現時点では固定しない。

- 詳細性能カウンターの具体的採取ツール
- アノテーション方式の具体実装
- 区間時間採取の具体方式
- 推定モデルのアルゴリズム
- 推定を shell で行うか外部ツールで行うか
- どの不足入力に対してどのフォールバック方式を採るか
- section / overlap category の標準語彙
- 区間ごとの補助アーティファクトの内部構造

これらは、手法差し替え可能性とロックイン回避の原則に従って、将来も複数方式を受け入れられる形で扱う。

The following are intentionally left open at this stage:

- the concrete tool for collecting detailed counters
- the concrete annotation mechanism
- the concrete way of collecting interval timings
- the estimation algorithm itself
- whether the estimation logic runs in shell or in an external tool
- which fallback method should be used for which missing input
- a standard vocabulary for section / overlap categories
- the internal schema of section-wise auxiliary artifacts

These are kept open so that multiple approaches remain possible under the principles of replaceability and avoiding lock-in.

## 8. 次に必要な詳細仕様 / Next Detailed Specifications

本書の次に必要なのは、少なくとも以下である。

1. [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md)
2. [`REESTIMATION_SPEC.md`](./REESTIMATION_SPEC.md)
3. [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md)
4. 推定結果画面の表示仕様
5. AI 最適化への推定結果受け渡し仕様

The next documents needed after this one include at least:

1. [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md)
2. [`REESTIMATION_SPEC.md`](./REESTIMATION_SPEC.md)
3. [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md)
4. a presentation specification for estimation result views
5. a handoff specification from estimation results to AI optimization
