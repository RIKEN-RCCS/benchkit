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

本書でいう推定パッケージは、推定モデル単体ではなく、計測入力の前提、必要入力、前処理、適用可能性判定、フォールバック方針、Estimate JSON への写像までを含む再利用単位である。

This document is a lower-level specification under [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md). It defines the unit by which BenchKit accepts, reuses, and replaces estimation methods.

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
- app 固有の補助入力がある場合の指定
- どうしても必要な特殊後処理

It should not be the default expectation that application developers write complex estimation logic in every `estimate.sh`.
The target design is that the application side only needs to specify:

- which estimation package to use
- how application-specific FOM or section names map into the package
- any application-specific auxiliary inputs
- any truly necessary special postprocessing

### 3.3 計測と推定の結合を明示する / Make Measurement-Estimation Coupling Explicit

推定方式は、必要な計測情報の取り方と強く結び付いている。
したがって BenchKit は、推定モデルだけでなく、どのような計測結果を前提にする方式かをパッケージとして明示できることが望ましい。

Estimation methods are strongly coupled with how the required measurement data is obtained.
Therefore BenchKit should preferably be able to represent not only the estimation model, but also the measurement assumptions of the method as part of the package.

### 3.4 Git 公開を前提にしない / Do Not Assume Git Publication

推定パッケージは、常に Git 管理下に置けるとは限らない。
将来アーキテクチャの仕様、ベンダー提供のツールチェイン、契約上の制約、非公開管理の必要性などにより、推定パッケージが以下の形を取ることを許容しなければならない。

- BenchKit と同じ公開リポジトリに同梱される package
- ローカルファイルとして配置される package
- 別の公開もしくは非公開リポジトリで管理される package
- ベンダー指定の配置や呼び出し方法に従う package
- 外部ツールや外部サービスを経由して実行される package

したがって BenchKit は、推定パッケージの内容そのものを常に Git に格納することを必須要件としてはならない。
BenchKit に求められるのは、推定パッケージの所在、識別情報、呼び出し契約、必要入力、適用条件を扱えることである。

An estimation package cannot always be stored under Git control.
Future-architecture specifications, vendor-provided toolchains, contractual restrictions, and private-management requirements may require packages to take forms such as:

- a package bundled in the same public repository as BenchKit
- a package stored as a local file
- a package managed in a separate public or private repository
- a package that follows vendor-specified placement or invocation rules
- a package executed through an external tool or service

Therefore BenchKit must not require that the package implementation itself always be stored in Git.
What BenchKit needs is the ability to handle the package location, identity, invocation contract, required inputs, and applicability conditions.

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

The package must define the inputs required for estimation.

It should preferably be able to express at least:

- mandatory inputs
- optional inputs
- auxiliary inputs
- external inputs

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

The package should preferably be able to map its information into at least the following Estimate JSON fields:

- `estimate_metadata`
- `measurement`
- `model`
- `applicability`
- `assumptions`
- `confidence`

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

- `section_breakdown_scaling`
- `annotated_interval_model`
- `external_counter_model`

これらは、深い分析や将来機評価に向く。

Examples:

- `section_breakdown_scaling`
- `annotated_interval_model`
- `external_counter_model`

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
- package metadata の完全な schema

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
3. 軽量パッケージの参照実装仕様
4. 詳細パッケージの参照実装仕様

The next documents needed after this one include at least:

1. [`ESTIMATION_PACKAGE_METADATA_SPEC.md`](./ESTIMATION_PACKAGE_METADATA_SPEC.md)
2. [`ESTIMATION_PACKAGE_SHELL_API_SPEC.md`](./ESTIMATION_PACKAGE_SHELL_API_SPEC.md)
3. a reference specification for lightweight packages
4. a reference specification for detailed packages
