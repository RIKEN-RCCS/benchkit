# 推定入力採取仕様 / Estimation Input Acquisition Specification

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

本書は [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md) および [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md) を補う下位仕様であり、推定に必要な入力をどのように採取し、どのように BenchKit へ受け渡すかを定義する。

本書の主眼は推定アルゴリズムそのものではなく、アプリ、BenchKit、推定パッケージの接続面を整理することである。

This document is a lower-level specification that complements [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md) and [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md), defining how inputs required for estimation are collected and handed off into BenchKit.

Its focus is not the estimation algorithm itself, but the interface boundary among the application, BenchKit, and estimation packages.

## 2. 目的 / Purpose

本仕様の目的は、推定入力採取を推定パッケージの内部ロジックから切り分け、アプリとの接続点を分かりやすくすることである。

少なくとも以下を達成することを目的とする。

- アプリ開発者がどこまで準備すればよいかを明確にする
- 推定パッケージ開発者がどの入力を期待してよいかを明確にする
- BenchKit がどの形式で入力を受け取り、保存し、引き渡すかを明確にする
- 入力採取失敗時の扱いを曖昧にしない
- 軽量推定と詳細推定の両方を同じ枠組みで扱えるようにする

The purpose of this specification is to separate estimation-input acquisition from estimation-package internals and make the connection point with applications clear.

It aims at least to:

- clarify what application developers need to prepare
- clarify what estimation-package developers may expect as inputs
- clarify how BenchKit receives, stores, and passes those inputs
- avoid ambiguity when input acquisition fails
- handle both lightweight and detailed estimation within the same framework

## 3. 基本原則 / Core Principles

### 3.1 推定入力採取と推定ロジックを分ける / Separate Input Acquisition from Estimation Logic

推定入力の採取方法と、採取済み入力をどう推定に使うかは区別して扱うべきである。

- 入力採取
  - 何を採るか
  - どこで採るか
  - どう保存するか
- 推定ロジック
  - 採取済み入力をどう解釈するか
  - どう補正するか
  - どう Estimate JSON へ写像するか

How estimation inputs are acquired and how already-acquired inputs are used for estimation should be treated separately.

- input acquisition
  - what is collected
  - where it is collected
  - how it is stored
- estimation logic
  - how collected inputs are interpreted
  - how they are adjusted
  - how they are mapped into Estimate JSON

### 3.2 app 側接続点を最小化する / Minimize the Application-Side Connection Surface

app 側は、推定入力採取のために必要以上に複雑なロジックを持つべきではない。
app 側は原則として、

- FOM
- section / overlap
- section ごとの補助データ参照
- 必要なら app 固有の補助メタデータ

を BenchKit に渡せればよい形を目指す。

The application side should not be forced to own unnecessarily complex logic merely for estimation input acquisition.
The target is that the application side only needs to provide:

- FOM
- sections / overlaps
- auxiliary data references per section
- application-specific auxiliary metadata when necessary

### 3.3 採取方式は差し替え可能である / Acquisition Methods Must Be Replaceable

BenchKit は、単一の採取方式に固定されてはならない。
少なくとも以下を受け入れられることが望ましい。

- アプリ自前の stdout 出力
- アプリ自前の補助 JSON / CSV / log
- 外部ツールによる trace / profile / counter dump
- site 側 wrapper や vendor tool による採取

BenchKit must not be fixed to a single acquisition method.
It should preferably be able to accept at least:

- application-emitted stdout
- application-emitted auxiliary JSON / CSV / logs
- traces / profiles / counter dumps from external tools
- acquisition through site-side wrappers or vendor tools

## 4. 入力採取の構成 / Structure of Input Acquisition

推定入力採取は、概念上、少なくとも以下からなる。

1. 採取対象
2. 採取主体
3. 採取タイミング
4. 受け渡し形式
5. 保存場所
6. 失敗時の扱い

Estimation input acquisition consists conceptually of at least:

1. acquisition target
2. acquisition actor
3. acquisition timing
4. handoff format
5. storage location
6. failure handling

### 4.1 採取対象 / Acquisition Targets

BenchKit は、少なくとも以下の入力種別を受け入れられることが望ましい。

- FOM
- section 時間
- overlap 時間
- section ごとの補助アーティファクト
- 詳細性能カウンター
- trace / profile
- 推定入力に必要な補助メタデータ

BenchKit should preferably be able to accept at least the following input kinds:

- FOM
- section timings
- overlap timings
- section-wise auxiliary artifacts
- detailed performance counters
- traces / profiles
- auxiliary metadata required for estimation input

### 4.2 採取主体 / Acquisition Actors

採取主体は少なくとも次を許容する。

- アプリ自前
- BenchKit の共通 shell
- 外部ツール
- site 側 wrapper
- vendor 提供ツール

The following acquisition actors should be allowed at minimum:

- the application itself
- BenchKit common shell
- external tools
- site-side wrappers
- vendor-provided tools

### 4.3 採取タイミング / Acquisition Timing

採取タイミングは少なくとも次を許容する。

- 実行中に stdout として出力
- 実行中に補助ファイルへ書き出し
- 実行後に postprocess で抽出
- 実行後に外部ツール出力から変換

The following timings should be allowed at minimum:

- emitted to stdout during execution
- written to auxiliary files during execution
- extracted by postprocessing after execution
- converted from external-tool output after execution

## 5. BenchKit への受け渡し方法 / Handoff into BenchKit

### 5.1 基本方針 / Basic Policy

BenchKit への受け渡し方法は、少なくとも次の 2 層で考える。

- Result JSON へ直接正規化される入力
- 推定専用の補助入力として補助ファイル / artifact として参照される入力

Handoff into BenchKit should be thought of in at least two layers:

- inputs normalized directly into Result JSON
- inputs referenced as estimation-specific auxiliary files or artifact data

### 5.2 Result JSON へ正規化する入力 / Inputs Normalized into Result JSON

少なくとも以下は、可能な限り Result JSON へ正規化されることが望ましい。

- FOM
- section
- overlap
- 実行条件に紐づく最低限のメタデータ

At minimum, the following should preferably be normalized into Result JSON whenever possible:

- FOM
- sections
- overlaps
- minimal metadata tied to execution conditions

### 5.3 補助入力として渡すもの / Inputs Passed as Auxiliary Data

以下は、必要に応じて補助入力として渡してよい。

- tgz 化されたカウンターデータ
- trace ファイル
- profile ファイル
- section ごとの生ログ
- package 固有の補助 JSON

The following may be passed as auxiliary inputs when needed:

- counter data archived as tgz
- trace files
- profile files
- raw logs per section
- package-specific auxiliary JSON

## 6. section / overlap 登録面 / Section and Overlap Registration Surface

### 6.1 section 登録 / Section Registration

section は単なる時間値ではなく、少なくとも概念上、次を一体として登録できることが望ましい。

- section 名
- 区間時間
- 当該区間に適用する推定パッケージ名
- 補助アーティファクト参照

たとえば、概念上は以下に近い登録面を許容すべきである。

```sh
bk_emit_section_time \
  --name compute_cpu_measure_atom_mass \
  --time 0.30 \
  --estimation-package counter_papi_detailed \
  --artifact results/papi_compute_cpu_measure_atom_mass.tgz
```

A section should preferably be registerable, at least conceptually, as a single unit containing:

- section name
- section time
- estimation package name applied to that section
- auxiliary artifact references

### 6.2 overlap 登録 / Overlap Registration

overlap も、少なくとも概念上、次を一体として登録できることが望ましい。

- 関与する section 群
- overlap 時間
- 当該 overlap に適用する推定パッケージ名
- 補助アーティファクト参照

Overlap should likewise preferably be registerable, at least conceptually, as a single unit containing:

- the participating sections
- overlap time
- estimation package name applied to the overlap
- auxiliary artifact references

### 6.3 現時点で固定しないこと / What Is Not Fixed Yet

現時点では、section / overlap の登録を

- stdout ベースで行うか
- 補助 JSON ベースで行うか
- shell 関数 API にするか

までは固定しない。
ただし、最終的に BenchKit が受け取る意味要素は上記のように揃っていることが望ましい。

At this stage, this document does not fix whether section / overlap registration is:

- stdout-based
- auxiliary-JSON-based
- exposed as a shell function API

However, the semantic elements ultimately received by BenchKit should preferably be aligned as described above.

## 7. 失敗時の扱い / Failure Handling

### 7.1 採取失敗と実行失敗を分ける / Distinguish Acquisition Failure from Execution Failure

推定入力採取失敗とアプリ実行失敗は区別して扱うべきである。

- アプリ実行は成功
- しかし詳細入力採取は失敗

という状況を表現できることが望ましい。

Estimation-input acquisition failure should be distinguishable from application execution failure.
It should be possible to represent cases such as:

- application execution succeeded
- but detailed-input acquisition failed

### 7.2 最低限の返し方 / Minimum Required Outcomes

採取失敗時には、少なくとも次のいずれかを明示すべきである。

- 軽量推定へフォールバック可能
- 再計測が必要
- 当該詳細 package は不適用

When acquisition fails, at least one of the following should be made explicit:

- fallback to lightweight estimation is possible
- re-measurement is required
- the detailed package is not applicable

## 8. 責務分担 / Responsibility Split

### 8.1 app 開発者の責務 / Application Developer Responsibility

app 開発者は、原則として次を整えればよい。

- FOM を出せること
- section / overlap を出せること
- 必要なら補助アーティファクトの参照を渡せること
- app 固有 section 名を定義できること

The application developer should generally only need to ensure:

- FOM can be emitted
- sections / overlaps can be emitted
- auxiliary artifact references can be passed when needed
- application-specific section names can be defined

### 8.2 推定パッケージ開発者の責務 / Estimation Package Developer Responsibility

推定パッケージ開発者は、原則として次を定義する。

- どの入力を必要とするか
- 補助アーティファクトをどう解釈するか
- どの採取失敗をフォールバック可能とみなすか
- section / overlap をどう解釈するか

The estimation-package developer is generally responsible for defining:

- which inputs are required
- how auxiliary artifacts are interpreted
- which acquisition failures are considered fallback-eligible
- how sections / overlaps are interpreted

### 8.3 BenchKit の責務 / BenchKit Responsibility

BenchKit は、原則として次を担う。

- Result JSON への正規化
- 補助アーティファクト参照の保持
- 入力不足時の判定支援
- 推定パッケージへの受け渡し
- 保存形式と表示形式の統一

BenchKit is generally responsible for:

- normalization into Result JSON
- retention of auxiliary artifact references
- support for missing-input evaluation
- handoff into estimation packages
- unified storage and presentation formats

## 9. 現時点で固定しないこと / Items Intentionally Left Open

本書は以下を現時点では固定しない。

- section / overlap 登録 API の最終シンタックス
- artifact の内部フォーマット
- counter / trace / profile の標準ファイル形式
- site 側 wrapper と app 側実装の最終分担
- stdout と補助ファイルのどちらを主経路にするか

This document intentionally does not yet fix:

- the final syntax of the section / overlap registration API
- the internal artifact format
- standard file formats for counter / trace / profile data
- the final split between site-side wrappers and application-side implementation
- whether stdout or auxiliary files should be the primary path

## 10. 次に必要な具体仕様 / Next Detailed Specifications

本書の次に必要なのは、少なくとも以下である。

1. section / overlap 登録 API の具体仕様
2. 補助アーティファクト参照の具体仕様
3. app 側 `estimate.sh` / `run.sh` 接続例
4. detailed package 向けの入力採取参照実装仕様

The next documents needed after this one include at least:

1. a concrete specification for section / overlap registration APIs
2. a concrete specification for auxiliary artifact references
3. example connection patterns for application-side `estimate.sh` / `run.sh`
4. a reference acquisition spec for detailed packages
