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
本書は、推定手法の内部アルゴリズムそのものを固定する文書ではなく、BenchKit が推定機能を受け入れ、実行し、保存し、表示するための共通契約を定義する。

This document is a lower-level specification that details the estimation function described in [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md).
It does not fix a single estimation algorithm. Instead, it defines the common contract by which BenchKit accepts, runs, stores, and presents estimation functions.

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
  section、overlap、詳細性能カウンター、アノテーション区間時間などを使う推定

Estimation should not always assume detailed counters or detailed annotations.
At minimum, the following stages should be able to coexist:

- lightweight estimation:
  estimation from a small number of inputs such as FOM, node count, and known comparison baselines
- detailed estimation:
  estimation using section, overlap, detailed counters, or annotated interval timings

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

## 4. 推定機能の構成 / Components of the Estimation Function

性能推定機能は、概念上、以下の構成要素からなる。

1. 推定入力
2. 計測メタデータ
3. 推定モデル
4. 比較基準
5. 推定結果
6. 履歴と再推定

Conceptually, the estimation function consists of:

1. estimation input
2. measurement metadata
3. estimation model
4. comparison baseline
5. estimation output
6. history and re-estimation

### 4.1 推定入力 / Estimation Input

推定入力は、最低限、Result JSON を起点とする。
将来的には、追加の性能カウンター、アノテーション区間時間、外部ファイル、外部サービスの結果を補助入力として使ってもよい。

Result JSON is the minimum required input.
In the future, additional counters, annotated interval timings, external files, or external service outputs may be used as auxiliary inputs.

### 4.2 計測メタデータ / Measurement Metadata

推定に使う計測入力については、少なくとも以下を識別できることが望ましい。

- どのツールで採取したか
- どの方式で採取したか
- 軽量採取か詳細採取か
- アノテーションの有無
- 区間時間が実測か推定か

For measurement inputs used by estimation, it should be possible to identify at least:

- which tool collected them
- which method was used
- whether the collection was lightweight or detailed
- whether annotations were used
- whether interval times were measured or inferred

### 4.3 推定モデル / Estimation Model

推定モデルは、BenchKit に埋め込まれた単一モデルである必要はない。
アプリ固有スクリプト、共通 shell ライブラリ、外部ツール、外部サービスのいずれでもよい。

ただし BenchKit から見て、少なくとも以下を識別可能にすべきである。

- モデル種別
- モデル名
- モデル版
- スケーリング方式
- 将来システム仮定

The estimation model need not be a single built-in BenchKit model.
It may be an application-specific script, a shared shell library, an external tool, or an external service.

However, from the perspective of BenchKit, the following should be identifiable:

- model type
- model name
- model version
- scaling method
- future-system assumption

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

### 4.5 履歴と再推定 / History and Re-Estimation

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

用途:

- 高頻度実行
- PoC
- 準備が進んでいない app

### 5.2 詳細推定 / Detailed Estimation

入力:

- section / overlap
- 詳細性能カウンター
- アノテーション区間時間
- より複雑なモデルや外部モデル

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

Typical use:

- high-frequency execution
- PoC
- applications not yet fully prepared

### 5.2 Detailed Estimation

Inputs:

- section / overlap
- detailed performance counters
- annotated interval timings
- more complex or external models

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

## 7. 現時点で未確定の事項 / Items Intentionally Left Open

以下は現時点では固定しない。

- 詳細性能カウンターの具体的採取ツール
- アノテーション方式の具体実装
- 区間時間採取の具体方式
- 推定モデルのアルゴリズム
- 推定を shell で行うか外部ツールで行うか

これらは、手法差し替え可能性とロックイン回避の原則に従って、将来も複数方式を受け入れられる形で扱う。

The following are intentionally left open at this stage:

- the concrete tool for collecting detailed counters
- the concrete annotation mechanism
- the concrete way of collecting interval timings
- the estimation algorithm itself
- whether the estimation logic runs in shell or in an external tool

These are kept open so that multiple approaches remain possible under the principles of replaceability and avoiding lock-in.

## 8. 次に必要な詳細仕様 / Next Detailed Specifications

本書の次に必要なのは、少なくとも以下である。

1. [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md)
2. 推定結果画面の表示仕様
3. 再推定トリガ仕様
4. AI 最適化への推定結果受け渡し仕様

The next documents needed after this one include at least:

1. [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md)
2. a presentation specification for estimation result views
3. a re-estimation trigger specification
4. a handoff specification from estimation results to AI optimization
