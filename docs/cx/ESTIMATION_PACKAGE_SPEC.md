# 推定パッケージ仕様 / Estimation Package Specification

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

本書は [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md) の下位仕様であり、BenchKit が推定方式をどのような単位で受け入れ、再利用し、差し替えるかを定義する。
推定入力をどのように採取し BenchKit へ受け渡すかは、[`ESTIMATION_INPUT_ACQUISITION_SPEC.md`](./ESTIMATION_INPUT_ACQUISITION_SPEC.md) を参照する。

本書でいう推定パッケージは、推定モデル単体ではなく、計測入力の前提、必要入力、前処理、適用可能性判定、フォールバック方針、Estimate JSON への写像までを含む再利用単位である。

This document is a lower-level specification under [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md). It defines the unit by which BenchKit accepts, reuses, and replaces estimation methods.
For how estimation inputs are acquired and handed into BenchKit, see [`ESTIMATION_INPUT_ACQUISITION_SPEC.md`](./ESTIMATION_INPUT_ACQUISITION_SPEC.md).

An estimation package in this document is not just an estimation model. It is a reusable unit that includes measurement prerequisites, required inputs, preprocessing, applicability evaluation, fallback policy, and mapping into Estimate JSON.

## 2. 目的 / Purpose

推定パッケージ仕様の目的は、推定方式と計測方式が実質的に一体であることを前提にしつつ、アプリ開発者が `estimate.sh` に過度な責務を持たなくて済む形で推定機能を共通化することである。

本仕様は、少なくとも以下を目指す。

- 推定方式の差し替えを容易にする
- 計測方式と推定方式の組を再利用可能にする
- app ごとの `estimate.sh` の責務を最小化する
- 推定方式ごとの必要入力と不足時の扱いを明確にする
- 軽量推定と詳細推定を同じ枠組みで扱えるようにする

The purpose of the estimation package specification is to standardize estimation functionality while recognizing that estimation methods and measurement methods are practically coupled, and at the same time reduce the burden placed on application-specific `estimate.sh`.

This specification aims at least to:

- make estimation-method replacement easy
- make combinations of measurement and estimation reusable
- minimize per-application `estimate.sh` responsibilities
- clarify required inputs and missing-input behavior for each method
- handle lightweight and detailed estimation within the same framework

## 3. 基本原則 / Core Principles

### 3.1 推定パッケージは再利用単位である / Estimation Packages Are Reusable Units

推定パッケージは、単一のアルゴリズム名ではなく、少なくとも以下を束ねた再利用単位として扱う。

- 想定する計測入力
- 必要入力の集合
- 入力前処理
- 推定実行方法
- フォールバック方針
- Estimate JSON への出力規約

An estimation package is treated not as a single algorithm name, but as a reusable unit that bundles at least:

- expected measurement inputs
- the required input set
- input preprocessing
- estimation execution behavior
- fallback policy
- output rules into Estimate JSON

### 3.2 app 側責務の最小化 / Minimizing Application-Side Responsibility

アプリ開発者が毎回 `estimate.sh` に複雑な推定ロジックを書くことは基本としない。
app 側は、原則として以下のみを記述すればよい形を目指す。

- どの推定パッケージを使うか
- app 固有の FOM 名や section 名との対応
- 区間ごとにどの推定パッケージを適用するか
- 必要なら区間ごとの補助データ参照
- app 固有の補助入力がある場合の指定
- どうしても必要な特殊後処理

It should not be the default expectation that application developers write complex estimation logic in every `estimate.sh`.
The target design is that the application side only needs to specify:

- which estimation package to use
- how application-specific FOM or section names map into the package
- which estimation package is applied to each section
- auxiliary data references for each section when needed
- any application-specific auxiliary inputs
- any truly necessary special postprocessing

### 3.3 計測と推定の結合を明示する / Make Measurement-Estimation Coupling Explicit

推定方式は、必要な計測情報の取り方と強く結び付いている。
したがって BenchKit は、推定モデルだけでなく、どのような計測結果を前提にする方式かをパッケージとして明示できることが望ましい。

Estimation methods are strongly coupled with how the required measurement data is obtained.
Therefore BenchKit should preferably be able to represent not only the estimation model, but also the measurement assumptions of the method as part of the package.

### 3.3.1 取得方式ごとの詳細パッケージ / Detailed Packages by Acquisition Path

詳細推定パッケージは、単に「詳細推定」でひとまとめにせず、少なくとも取得方式ごとに区別できることが望ましい。
たとえば以下のような区別を許容すべきである。

- `instrumented_app_sections`
  - アプリ自前の区間時間や区間別結果を入力とする package
- `instrumented_tool_sections`
  - Caliper などの外部ツール由来の区間時間や区間別結果を入力とする package
- `counter_based`
  - 特定区間に対して採取された詳細性能カウンターを入力とする package

Detailed estimation packages should not be grouped together as a single undifferentiated category.
They should preferably be distinguishable at least by acquisition path, for example:

- `instrumented_app_sections`
  - packages that use application-defined interval timings or section-wise results
- `instrumented_tool_sections`
  - packages that use interval timings or section-wise results from external tools such as Caliper
- `counter_based`
  - packages that use detailed counters collected for specific sections

### 3.3.2 区間ごとの複合推定 / Section-Wise Composite Estimation

推定パッケージは、単一手法だけでなく、区間ごとに異なる推定方式を束ねる複合パッケージであってもよい。
特に以下を許容すべきである。

- ある区間はカウンターベース
- 別の区間はトレースベース
- その他の区間は区間時間ベース

この場合、BenchKit は最終 FOM が複数区間の推定結果の合成であることを受け入れられるべきである。

An estimation package may be a composite package that combines different estimation methods for different sections, rather than a single method.
In particular, the framework should allow cases such as:

- one section estimated with counter-based methods
- other sections estimated with trace-based methods
- other sections estimated from interval timings

In such cases, BenchKit should be able to accept that the final FOM is composed from multiple section-wise estimation results.

overlap 区間も、section ごとの複合推定の一部として扱ってよい。
すなわち、overlap は単なる補正値に限らず、二つ以上の section が同時進行しうる区間として独立した推定部品で表現してよい。

Overlap regions may also be treated as part of section-wise composite estimation.
That is, overlap need not be treated only as a correction value; it may instead be represented as an independent estimation component for a region in which two or more sections can progress simultaneously.

### 3.3.3 現行システム側モデルと将来システム側モデル / Current-Side and Future-Side Models

推定パッケージは、`current_system` 側と `future_system` 側に対して常に同一の推定規則を適用しなければならないわけではない。

少なくとも次の二種類を区別できることが望ましい。

- `intra_system_scaling_model`
  - benchmark result を同種または同一系統のシステム上の target nodes へ伸長する package または package 内部部品
- `cross_system_projection_model`
  - 別系統または別アーキテクチャの benchmark result から対象システム上の target へ投影する package または package 内部部品

ここで、`current_system` 側も `future_system` 側も、どちらの種類のモデルを使ってもよい。
単一 package が両方を内部で扱ってもよいし、`current_system` 側と `future_system` 側で別々の package を選択してもよい。

An estimation package need not always apply the same estimation rule to the `current_system` side and the `future_system` side.

It is desirable to distinguish at least the following two kinds:

- `intra_system_scaling_model`
  - a package or internal package component that scales a benchmark result to target nodes on the same or closely related system line
- `cross_system_projection_model`
  - a package or internal package component that projects from a benchmark result on a different system line or architecture to the target system

Here, either kind of model may be used on either the `current_system` side or the `future_system` side.
A single package may handle both internally, or separate packages may be selected for the `current_system` side and the `future_system` side.

また、package または package 内部部品は、少なくとも次の system 整合条件を定義できることが望ましい。

- `source_system_scope`
  - どの system を入力 benchmark result として受け入れるか
- `target_system_scope`
  - どの system を推定出力側の対象として受け入れるか
- `system_compatibility_rule`
  - 同一 system のみ許容するのか、同一系統を許容するのか、異種 system 間投影を許容するのか

これにより、たとえば `intra_system_scaling_model` では「Fugaku -> Fugaku」は許容し、「RC_GH200 -> Fugaku」は不適用とできる。
一方 `cross_system_projection_model` では「RC_GH200 -> FugakuNEXT」を許容しつつ、向きが逆の指定を不適用とできる。

In addition, a package or internal package component should preferably be able to define at least the following system-consistency conditions:

- `source_system_scope`
  - which systems are accepted as input benchmark-result systems
- `target_system_scope`
  - which systems are accepted as output-side target systems
- `system_compatibility_rule`
  - whether only the same system is allowed, the same system line is allowed, or cross-system projection is allowed

This makes it possible, for example, for an `intra_system_scaling_model` to allow `Fugaku -> Fugaku` while rejecting `RC_GH200 -> Fugaku`, and for a `cross_system_projection_model` to allow `RC_GH200 -> FugakuNEXT` while rejecting the reversed direction.

### 3.4 Git 公開を前提にしない / Do Not Assume Git Publication

推定パッケージは、常に Git 管理下に置けるとは限らない。
将来アーキテクチャの仕様、ベンダー提供のツールチェイン、契約上の制約、非公開管理の必要性などにより、推定パッケージが以下の形を取ることを許容しなければならない。

- BenchKit と同じ公開リポジトリに同梱される package
- ローカルファイルとして配置される package
- 別の公開もしくは非公開リポジトリで管理される package
- ベンダー指定の配置や呼び出し方法に従う package
- 外部ツールや外部サービスを経由して実行される package

したがって BenchKit は、推定パッケージの内容そのものを常に Git に格納することを必須要件としてはならない。
BenchKit に求められるのは、推定パッケージの所在、識別情報、呼び出し規約、必要入力、適用条件を扱えることである。

An estimation package cannot always be stored under Git control.
Future-architecture specifications, vendor-provided toolchains, contractual restrictions, and private-management requirements may require packages to take forms such as:

- a package bundled in the same public repository as BenchKit
- a package stored as a local file
- a package managed in a separate public or private repository
- a package that follows vendor-specified placement or invocation rules
- a package executed through an external tool or service

Therefore BenchKit must not require that the package implementation itself always be stored in Git.
What BenchKit needs is the ability to handle the package location, identity, invocation rules, required inputs, and applicability conditions.

## 4. 推定パッケージの論理構成 / Logical Structure of an Estimation Package

推定パッケージは、概念上、少なくとも以下の要素を持つ。

1. パッケージ識別情報
2. 対応する計測方式
3. 必要入力定義
4. 入力前処理
5. 適用可能性判定
6. フォールバック方針
7. 推定実行
8. Estimate JSON への写像

An estimation package conceptually contains at least:

1. package identity
2. associated measurement method
3. required-input definition
4. input preprocessing
5. applicability evaluation
6. fallback policy
7. estimation execution
8. mapping into Estimate JSON

### 4.1 パッケージ識別情報 / Package Identity

少なくとも以下を識別できることが望ましい。

- パッケージ名
- パッケージ版
- 推定方式種別
- 詳細度

At least the following should preferably be identifiable:

- package name
- package version
- estimation-method class
- detail level

これらは、原則として [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md) の `estimate_metadata` および `model` に写像できることが望ましい。

These should preferably be mappable, in principle, into `estimate_metadata` and `model` defined in [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md).

### 4.2 対応する計測方式 / Associated Measurement Method

パッケージは、どのような計測方式を前提とするかを保持できることが望ましい。

例:

- FOM のみを使う簡易推定
- section / overlap を使う推定
- 詳細性能カウンターを使う推定
- アノテーション区間時間を使う推定

The package should preferably capture what measurement method it assumes.

Examples:

- lightweight estimation using only FOM
- estimation using section / overlap
- estimation using detailed performance counters
- estimation using annotated interval timings

### 4.3 必要入力定義 / Required Input Definition

パッケージは、推定に必要な入力を明示しなければならない。

少なくとも以下を表現できることが望ましい。

- 必須入力
- 任意入力
- 補助入力
- 外部入力
- 区間ごとの必要入力
- 区間ごとの補助データ参照

The package must define the inputs required for estimation.

It should preferably be able to express at least:

- mandatory inputs
- optional inputs
- auxiliary inputs
- external inputs
- section-wise required inputs
- section-wise auxiliary data references

### 4.4 適用可能性判定 / Applicability Evaluation

パッケージは、与えられた入力に対して適用可能かどうかを判定できなければならない。

少なくとも以下を返せることが望ましい。

- 適用可能
- フォールバック適用可能
- 不適用
- 再計測または追加準備が必要

The package must be able to evaluate whether it is applicable to the provided inputs.

It should preferably be able to return at least:

- applicable
- applicable with fallback
- not applicable
- re-measurement or additional preparation required

### 4.5 フォールバック方針 / Fallback Policy

パッケージは、必要入力が不足していた場合に、どの軽量方式へフォールバックしてよいか、あるいはフォールバックせず停止すべきかを定義できることが望ましい。

The package should preferably be able to define which lighter-weight method may be used as fallback when required inputs are missing, or whether execution must stop without fallback.

### 4.6 Estimate JSON への写像 / Mapping into Estimate JSON

パッケージは、少なくとも以下の Estimate JSON 項目へ情報を写像できることが望ましい。

- `estimate_metadata`
- `measurement`
- `model`
- `applicability`
- `assumptions`
- `confidence`
- `fom_breakdown.sections`
- `fom_breakdown.overlaps`

必要に応じて、package は top-level `model` だけでなく `current_system.model` と `future_system.model` にも情報を写像してよい。

When needed, a package may map information not only into the top-level `model`, but also into `current_system.model` and `future_system.model`.

The package should preferably be able to map its information into at least the following Estimate JSON fields:

- `estimate_metadata`
- `measurement`
- `model`
- `applicability`
- `assumptions`
- `confidence`
- `fom_breakdown.sections`
- `fom_breakdown.overlaps`

## 5. BenchKit における責務分担 / Responsibility Split in BenchKit

### 5.1 フレームワーク側責務 / Framework-Side Responsibilities

BenchKit 側は、原則として以下を提供することが望ましい。

- 推定パッケージの登録機構
- 推定パッケージの呼び出し機構
- 必要入力判定の共通処理
- フォールバック処理の共通枠組み
- Estimate JSON の標準化
- パッケージ識別情報の保持

BenchKit should preferably provide the following:

- a registration mechanism for estimation packages
- an invocation mechanism for estimation packages
- common handling for required-input evaluation
- a common framework for fallback handling
- Estimate JSON standardization
- retention of package identity metadata

### 5.2 app 側責務 / Application-Side Responsibilities

app 側の責務は、原則として以下に留めることが望ましい。

- 使用する推定パッケージの選択
- app 固有の FOM / section 対応付け
- app 固有の補助入力指定
- 最小限の特殊処理

The application side should preferably be limited to:

- selecting the estimation package to use
- mapping application-specific FOM or section names
- specifying application-specific auxiliary inputs
- minimal special handling

### 5.3 推定パッケージ開発者側責務 / Estimation-Package-Developer Responsibilities

推定パッケージ開発者の責務は、原則として以下を定義することにある。

- 当該 package が前提とする計測方式
- 具体的な必要入力と不足時の判定条件
- section / overlap の解釈規約
- 区間ごとの推定部品の合成規則
- 補助アーティファクトの内部フォーマット
- 必要に応じたフォールバック規則

すなわち、BenchKit が共通ルールを提供し、app 側が package を選択し、package 開発者が推定方式の具体的意味を定める、という責務分離を基本とする。

The estimation-package developer is primarily responsible for defining:

- the measurement method assumed by the package
- the concrete required inputs and missing-input conditions
- the interpretation rules for sections and overlaps
- the composition rules for section-wise estimation components
- the internal format of auxiliary artifacts
- fallback rules when needed

In other words, the intended separation is that BenchKit provides the common rules, the application side selects the package, and the package developer defines the concrete meaning of the estimation method.

## 6. 推奨される導入形態 / Recommended Adoption Forms

### 6.1 軽量パッケージ / Lightweight Packages

例:

- `lightweight_fom_scaling`
- `baseline_ratio_estimation`

これらは、高頻度実行や PoC に向く。

Examples:

- `lightweight_fom_scaling`
- `baseline_ratio_estimation`

These are suitable for high-frequency runs and PoC work.

### 6.2 詳細パッケージ / Detailed Packages

例:

- `instrumented_app_sections`
- `instrumented_tool_sections`
- `counter_based_section_model`
- `trace_based_section_model`
- `composite_section_model`

これらは、深い分析や将来機評価に向く。

Examples:

- `instrumented_app_sections`
- `instrumented_tool_sections`
- `counter_based_section_model`
- `trace_based_section_model`
- `composite_section_model`

These are suitable for deeper analysis and future-system evaluation.

## 7. 参照実装イメージ / Reference Implementation Direction

BenchKit においては、将来的に app 側の `estimate.sh` が毎回すべてを書くのではなく、例えば以下のような形へ寄せることが望ましい。

```sh
BK_ESTIMATION_PACKAGE=lightweight_fom_scaling
BK_ESTIMATION_TARGET_SYSTEM=FutureSystemA

source scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh
bk_run_estimation_package
```

この形では、app 側はパッケージ選択と最小限の app 固有設定を担い、推定方式の詳細はパッケージ側へ集約される。

In BenchKit, a desirable future direction is that application-side `estimate.sh` no longer implements everything each time, but instead looks like:

```sh
BK_ESTIMATION_PACKAGE=lightweight_fom_scaling
BK_ESTIMATION_TARGET_SYSTEM=FutureSystemA

source scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh
bk_run_estimation_package
```

In this form, the application side is responsible only for package selection and minimal app-specific configuration, while the details of the estimation method are concentrated in the package.

## 8. 現時点で固定しないもの / Items Not Fixed Yet

本書は以下をまだ固定しない。

- パッケージの具体的なディレクトリ構成
- パッケージの配置形態が公開同梱、ローカルファイル、別公開または非公開リポジトリ、ベンダー提供、外部サービスのどれであるかの表現方式
- package ごとの shell API の詳細
- package を shell で書くか外部ツールで書くか
- package metadata の完全な構造

これらは、現行の `estimate_common.sh` と app 側 `estimate.sh` の実装経験を踏まえて段階的に固定する。

This document does not yet fix:

- the exact directory layout of packages
- the exact representation for whether a package is publicly bundled, local-file-based, managed in a separate public or private repository, vendor-provided, or externally hosted
- the detailed shell API of each package
- whether packages are written in shell or external tools
- the complete schema of package metadata

These should be fixed incrementally based on implementation experience with the current `estimate_common.sh` and application-side `estimate.sh`.

## 9. 次に必要な下位仕様 / Next Detailed Specifications

本書の次に必要なのは、少なくとも以下である。

1. [`ESTIMATION_PACKAGE_METADATA_SPEC.md`](./ESTIMATION_PACKAGE_METADATA_SPEC.md)
2. [`ESTIMATION_PACKAGE_SHELL_API_SPEC.md`](./ESTIMATION_PACKAGE_SHELL_API_SPEC.md)
3. [`ESTIMATION_INPUT_ACQUISITION_SPEC.md`](./ESTIMATION_INPUT_ACQUISITION_SPEC.md)
4. 軽量パッケージの参照実装仕様
5. 詳細パッケージの参照実装仕様

The next documents needed after this one include at least:

1. [`ESTIMATION_PACKAGE_METADATA_SPEC.md`](./ESTIMATION_PACKAGE_METADATA_SPEC.md)
2. [`ESTIMATION_PACKAGE_SHELL_API_SPEC.md`](./ESTIMATION_PACKAGE_SHELL_API_SPEC.md)
3. [`ESTIMATION_INPUT_ACQUISITION_SPEC.md`](./ESTIMATION_INPUT_ACQUISITION_SPEC.md)
4. a reference specification for lightweight packages
5. a reference specification for detailed packages
