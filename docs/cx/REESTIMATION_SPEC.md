# 再推定仕様 / Re-Estimation Specification

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

本書は [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md) の下位仕様であり、既存の benchmark result を再入力として推定をやり直す再推定フローを定義する。

This document is a lower-level specification under [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md). It defines the re-estimation flow that reruns estimation using an existing benchmark result as input.

## 2. 目的 / Purpose

再推定の目的は、同じ benchmark result に対して推定方式、推定モデル、推定条件、将来システム仮定を変更しながら比較可能な推定結果を得ることである。

主な用途は以下である。

- 推定モデル更新後の再評価
- 推定条件変更後の再評価
- 軽量推定と詳細推定の比較
- 将来システム仮定を変えた比較
- AI 駆動最適化での評価関数更新後の再評価

The purpose of re-estimation is to obtain comparable estimation results for the same benchmark result while varying the estimation method, estimation model, estimation conditions, or future-system assumptions.

Typical use cases include:

- re-evaluation after updating an estimation model
- re-evaluation after changing estimation conditions
- comparison between lightweight and detailed estimation
- comparison under different future-system assumptions
- re-evaluation after updating an AI-driven optimization objective

## 3. 基本原則 / Core Principles

### 3.1 benchmark result の固定 / Fixed Benchmark Result

再推定では、入力となる benchmark result を明示的に固定しなければならない。
この識別には、少なくとも result の UUID を用いることを基本とする。

In re-estimation, the input benchmark result must be explicitly fixed.
At minimum, the UUID of the result should be used as the primary identifier.

### 3.2 比較可能性 / Comparability

再推定結果は、元の benchmark result と結び付けられ、かつ複数の推定結果同士を比較できるようにしなければならない。

Re-estimation results must remain linked to the original benchmark result and must be comparable against other estimation results derived from the same input.

### 3.3 推定方式の差し替え / Replaceable Estimation Methods

再推定は、推定方式の差し替え可能性を前提とする。
すなわち、同じ UUID に対して、軽量推定、詳細推定、外部モデル推定などを並存させられることが望ましい。

Re-estimation assumes replaceable estimation methods.
For the same UUID, it should preferably support coexistence of lightweight estimation, detailed estimation, and external-model-based estimation.

### 3.4 入力適合性 / Input Applicability

再推定では、指定した推定方式に必要な入力が、元の benchmark result および関連データから取得可能かを判定できることが望ましい。

必要入力が不足する場合、再推定は少なくとも以下のいずれかとして扱わなければならない。

- 不適用
- フォールバック実行
- 再計測または追加準備待ち

不足した入力を暗黙に無視して成功扱いの推定結果を返してはならない。

Re-estimation should preferably be able to evaluate whether the required inputs for a requested estimation method are available from the original benchmark result and related data.

When required inputs are missing, re-estimation must treat the situation as at least one of the following:

- not applicable
- fallback execution
- waiting for re-measurement or additional preparation

It must not silently ignore missing inputs and still report a successful estimate.

## 4. 再推定フロー / Re-Estimation Flow

BenchKit における再推定の典型フローは以下である。

1. 利用者またはワークフローが対象 benchmark result の UUID を指定する
2. BenchKit が UUID に対応する Result JSON を取得する
3. 対象 app の `estimate.sh` を起動する
4. `Estimate JSON` を生成する
5. 生成結果を保存し、ポータルで参照可能にする

The typical re-estimation flow in BenchKit is:

1. a user or workflow specifies the UUID of a benchmark result
2. BenchKit fetches the corresponding Result JSON
3. the app-specific `estimate.sh` is invoked
4. an `Estimate JSON` is generated
5. the generated result is stored and made available through the portal

## 5. 入力要件 / Input Requirements

再推定では少なくとも以下を入力として扱う。

- `estimate_uuid`
- `code`

必要に応じて以下を追加で与えてよい。

- 推定方式識別子
- 将来システム識別子
- 推定条件
- 比較基準条件
- フォールバック方針

At minimum, re-estimation uses the following inputs:

- `estimate_uuid`
- `code`

Optionally, the following may also be supplied:

- estimation-method identifier
- future-system identifier
- estimation conditions
- baseline-selection conditions
- fallback policy

## 6. BenchKit における現行実装 / Current Implementation in BenchKit

現行実装では、以下の要素が存在する。

- `.gitlab-ci.yml` に `estimate_uuid` 変数がある
- `generate_estimate_from_uuid.sh` が専用 child pipeline を生成する
- `fetch_result_by_uuid.sh` が結果取得を行う
- `run_estimate.sh` が app ごとの `estimate.sh` を呼び出す
- `send_estimate.sh` が推定結果を結果サーバに送信する

In the current implementation, the following already exist:

- an `estimate_uuid` variable in `.gitlab-ci.yml`
- `generate_estimate_from_uuid.sh` to generate a dedicated child pipeline
- `fetch_result_by_uuid.sh` to fetch the result
- `run_estimate.sh` to invoke app-specific `estimate.sh`
- `send_estimate.sh` to send estimation results to the result server

## 7. 現行実装と仕様のギャップ / Gaps Between Current Implementation and the Intended Specification

### 7.1 UUID 取得 API の契約 / Contract for UUID-Based Result Retrieval

現行の `fetch_result_by_uuid.sh` は `${RESULT_SERVER}/api/result/${estimate_uuid}` を取得する前提になっている。
しかし、現時点のコードベース上では、この API 契約が明示的な仕様文書としては定義されておらず、結果サーバ側の公開口も明文化が弱い。

したがって、以下を明確化する必要がある。

- UUID で Result JSON を返す取得 API
- 認証要否
- confidential 結果の扱い
- 取得失敗時の振る舞い

The current `fetch_result_by_uuid.sh` assumes a `${RESULT_SERVER}/api/result/${estimate_uuid}` endpoint.
However, this contract is not yet clearly documented as a formal specification, and the result-server-side exposure is not clearly described.

The following therefore need to be clarified:

- a retrieval API that returns Result JSON by UUID
- whether authentication is required
- how confidential results are handled
- behavior on retrieval failure

### 7.2 推定結果の識別 / Identification of Re-Estimation Results

再推定結果には、少なくとも以下を含めることが望ましい。

- 元の benchmark result UUID
- 推定方式識別子
- 推定パッケージ識別子
- 推定実行時刻

これにより、同じ benchmark result から複数回再推定した履歴を区別しやすくする。

Re-estimation results should preferably include at least:

- the UUID of the original benchmark result
- an estimation-method identifier
- an estimation-package identifier
- the estimation execution timestamp

This makes it easier to distinguish multiple re-estimations from the same benchmark result.

### 7.3 比較表示の不足 / Missing Comparison Semantics

現時点では、推定結果一覧は存在するが、同じ benchmark result から派生した複数推定結果を比較する前提の表示仕様はまだ弱い。

At present, estimated results can be listed, but display semantics for comparing multiple estimation results derived from the same benchmark result are still weak.

### 7.4 必要入力不足時の扱いの不足 / Missing Semantics for Insufficient Inputs

現時点では、推定方式を変更した際に、その方式に必要な詳細カウンター、アノテーション区間時間、補助入力ファイルなどが不足していた場合の扱いが十分に仕様化されていない。

少なくとも以下を明確化する必要がある。

- 不適用として終了する条件
- 軽量方式へフォールバックしてよい条件
- 再計測や追加準備を要求する条件
- その判定結果を Estimate JSON やポータルへどう残すか

At present, the handling of missing detailed counters, annotated interval timings, or auxiliary input files required by a changed estimation method is not specified well enough.

At least the following need to be clarified:

- conditions for terminating as not applicable
- conditions under which fallback to a lighter method is allowed
- conditions that require re-measurement or additional preparation
- how the decision should be recorded in Estimate JSON and the portal

## 8. 推奨要件 / Recommended Requirements

BenchKit における再推定は、少なくとも以下を満たすことが望ましい。

1. UUID 指定で benchmark result を再取得できること
2. app ごとの `estimate.sh` を同じ入力に対して繰り返し実行できること
3. 再推定結果に、元 benchmark result UUID を残せること
4. 異なる推定方式を同じ benchmark result に対して併存させられること
5. 軽量推定と詳細推定を同一の比較軸で扱えること
6. 必要入力不足時に、不適用・フォールバック・再計測要求を明示できること

Re-estimation in BenchKit should preferably satisfy at least:

1. the benchmark result can be re-fetched by UUID
2. app-specific `estimate.sh` can be run repeatedly for the same input
3. the re-estimation result can retain the original benchmark-result UUID
4. different estimation methods can coexist for the same benchmark result
5. lightweight and detailed estimation can be compared along the same comparison axis
6. insufficient inputs can be reported explicitly as not applicable, fallback, or re-measurement required

## 9. 次の実装候補 / Next Implementation Candidates

次に候補となる実装は以下である。

1. UUID 指定取得 API の仕様化と実装確認
2. Estimate JSON に benchmark result UUID と estimation method 識別を明示的に載せる
3. 再推定結果どうしを比較する表示仕様を定義する
4. portal から再推定を起動する要求フローを定義する

Candidate next steps include:

1. specify and verify the UUID-based result retrieval API
2. explicitly carry the benchmark-result UUID and estimation-method identity in Estimate JSON
3. define a display specification for comparing re-estimation results
4. define a portal-driven request flow for starting re-estimation
