# 推定パッケージ shell API 仕様 / Estimation Package Shell API Specification

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

本書は [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md) の下位仕様であり、BenchKit と推定パッケージの間でやり取りする shell API の最小規約を定義する。

This document is a lower-level specification under [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md). It defines the minimum shell API conventions between BenchKit and estimation packages.

## 2. 目的 / Purpose

本 API の目的は、推定パッケージごとの差を吸収しつつ、`scripts/estimation/common.sh` や app 側 `estimate.sh` から一貫した呼び出しができるようにすることである。

The purpose of this API is to allow consistent invocation from `scripts/estimation/common.sh` and application-side `estimate.sh` while absorbing differences among estimation packages.

## 3. 基本方針 / Basic Policy

shell API は最初から複雑にしすぎない。
初期段階では、以下の 4 段階を明示できればよい。

1. metadata 公開
2. 適用可能性判定
3. 推定実行
4. Estimate JSON への反映

The shell API should not be made overly complex from the start.
At the initial stage, it is sufficient to make the following four phases explicit:

1. metadata exposure
2. applicability evaluation
3. estimation execution
4. propagation into Estimate JSON

また、この shell API は推定パッケージの実装本体が常にリポジトリ内 shell ファイルであることを前提にしない。
package の実体は、リポジトリ内 shell、ローカルファイル、ベンダー指定ラッパー、外部サービス呼び出しのいずれであってもよく、shell API はそれらを BenchKit から統一的に扱うための境界面として定義する。

This shell API also does not assume that the implementation body of a package is always a shell file inside the repository.
The package body may instead be a repository shell file, a local file, a vendor-specified wrapper, or an external service call, and the shell API is defined as the interface boundary through which BenchKit handles them uniformly.

## 4. 推奨 API / Recommended API

### 4.1 `bk_estimation_package_metadata`

推定パッケージの metadata を返す。

返り値は、少なくとも [`ESTIMATION_PACKAGE_METADATA_SPEC.md`](./ESTIMATION_PACKAGE_METADATA_SPEC.md) に沿った情報を表現できることが望ましい。

Returns the metadata of the estimation package.

The return value should preferably be able to express at least the information defined in [`ESTIMATION_PACKAGE_METADATA_SPEC.md`](./ESTIMATION_PACKAGE_METADATA_SPEC.md).

### 4.2 `bk_estimation_package_check_applicability`

現在の入力に対して、適用可能かどうかを判定する。

少なくとも以下の状態を返せることが望ましい。

- `applicable`
- `fallback`
- `not_applicable`
- `needs_remeasurement`

Evaluates whether the package is applicable to the current inputs.

It should preferably be able to return at least:

- `applicable`
- `fallback`
- `not_applicable`
- `needs_remeasurement`

### 4.3 `bk_estimation_package_run`

推定本体を実行する。

この関数は、少なくとも以下を設定できることが望ましい。

- `est_current_*`
- `est_future_*`
- `est_current_fom_breakdown`
- `est_future_fom_breakdown`
- `est_measurement_json`
- `est_model_json`
- `est_assumptions_json`
- `est_confidence_json`

Runs the estimation itself.

This function should preferably be able to set at least:

- `est_current_*`
- `est_future_*`
- `est_current_fom_breakdown`
- `est_future_fom_breakdown`
- `est_measurement_json`
- `est_model_json`
- `est_assumptions_json`
- `est_confidence_json`

### 4.4 `bk_estimation_package_apply_metadata`

Estimate JSON に必要な metadata を共通変数へ反映する。

少なくとも以下を設定できることが望ましい。

- `est_estimation_id`
- `est_estimation_timestamp`
- `est_method_class`
- `est_detail_level`
- `est_estimation_package`
- `est_estimation_package_version`
- 必要に応じて `est_applicability_json`

Applies metadata required by Estimate JSON into shared variables.

It should preferably be able to set at least:

- `est_estimation_id`
- `est_estimation_timestamp`
- `est_method_class`
- `est_detail_level`
- `est_estimation_package`
- `est_estimation_package_version`
- `est_applicability_json` when needed

## 5. 呼び出し順序 / Invocation Order

初期段階では、以下の順を推奨する。

1. `bk_estimation_package_metadata`
2. `bk_estimation_package_check_applicability`
3. 必要ならフォールバック選択
4. `bk_estimation_package_run`
5. `bk_estimation_package_apply_metadata`
6. `print_json`

At the initial stage, the following order is recommended:

1. `bk_estimation_package_metadata`
2. `bk_estimation_package_check_applicability`
3. fallback selection if needed
4. `bk_estimation_package_run`
5. `bk_estimation_package_apply_metadata`
6. `print_json`

## 6. app 側 `estimate.sh` の最小責務 / Minimal Responsibility of Application-Side `estimate.sh`

app 側 `estimate.sh` は、将来的には少なくとも以下だけで済むことが望ましい。

- section / overlap と `estimation_package` の割当て宣言
- target system や target nodes など、app 固有の既定値の宣言
- 必要に応じた `run.sh` からの読込み
- 共通の呼び出し順序に従った実行

In the future, application-side `estimate.sh` should preferably be limited to:

- declaring section / overlap to `estimation_package` assignments
- declaring minimal app-specific defaults such as target system or target nodes
- being sourced from `run.sh` when needed
- executing according to the common invocation order

## 7. 参照イメージ / Reference Shape

```sh
BK_ESTIMATION_PACKAGE=weakscaling
source scripts/estimation/common.sh
source scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh

read_values "$1"
bk_estimation_package_metadata
bk_estimation_package_check_applicability
bk_estimation_package_run
bk_estimation_package_apply_metadata
print_json > "$output_file"
```

上記はリポジトリ内 shell package の例である。
ローカル配置やベンダー提供 package の場合も、最終的に同等の shell API 規約を満たすアダプタを介して呼び出せればよい。

The example above shows a repository-local shell package.
For local or vendor-provided packages, it is sufficient to invoke them through an adapter that satisfies the same shell API conventions.

## 8. 現時点で固定しないもの / Items Not Fixed Yet

本書は以下をまだ固定しない。

- 関数の返り方を標準出力にするか変数設定にするか
- 失敗時終了コードの詳細
- package 読み込み規約の詳細
- 共通 fallback 選択器の有無

This document does not yet fix:

- whether functions return via stdout or shared variables
- detailed exit-code behavior on failure
- the details of package-loading conventions
- whether a common fallback selector exists
- the exact adapter style for local, vendor-provided, or service-backed packages
