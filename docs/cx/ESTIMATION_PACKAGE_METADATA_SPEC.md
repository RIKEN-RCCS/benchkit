# 推定パッケージ metadata 仕様 / Estimation Package Metadata Specification

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

本書は [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md) の下位仕様であり、推定パッケージが宣言すべき metadata の最小要件を定義する。

This document is a lower-level specification under [`ESTIMATION_PACKAGE_SPEC.md`](./ESTIMATION_PACKAGE_SPEC.md). It defines the minimum metadata requirements that an estimation package should declare.

## 2. 目的 / Purpose

推定パッケージ metadata の目的は、BenchKit が推定パッケージを登録し、選択し、比較し、将来的に置き換え可能な形で扱えるようにすることである。

主な用途は以下である。

- パッケージ識別
- 必要入力の宣言
- 適用可能性判定の前提共有
- フォールバック方針の共有
- Estimate JSON への写像の補助

The purpose of estimation-package metadata is to allow BenchKit to register, select, compare, and replace estimation packages in a consistent way.

Typical uses include:

- package identification
- declaration of required inputs
- sharing prerequisites for applicability evaluation
- sharing fallback policy
- assisting mapping into Estimate JSON

## 3. 基本方針 / Basic Policy

推定パッケージ metadata は、最小必須項目と将来拡張項目からなる。
最初の段階では、アプリ開発者が理解しやすく shell からも扱いやすい最小集合に留める。

Estimation-package metadata consists of minimum required fields and future extension fields.
At the initial stage, it should remain a small set that is easy for application developers to understand and easy to handle from shell.

## 4. 最小必須項目 / Minimum Required Fields

推定パッケージ metadata は少なくとも以下を持たなければならない。

- `name`
- `version`
- `method_class`
- `detail_level`
- `required_inputs`
- `fallback_policy`

Estimation-package metadata must contain at least:

- `name`
- `version`
- `method_class`
- `detail_level`
- `required_inputs`
- `fallback_policy`

### 4.1 name

パッケージの一意識別に使う名前である。

例:

- `weakscaling`
- `section_breakdown_scaling`

This is the name used to identify the package.

### 4.2 version

パッケージの版である。Estimate JSON の `estimate_metadata.estimation_package_version` へ写像できることが望ましい。

This is the package version. It should preferably be mappable to `estimate_metadata.estimation_package_version` in Estimate JSON.

### 4.3 method_class

推定方式の大分類である。
現状実装では `weakscaling` のような最小経路も `lightweight` に分類されるが、これは FOM-only 推定を意味しない。

初期段階では少なくとも以下を推奨する。

- `lightweight` (`weakscaling` を最小経路とする class)
- `detailed`
- `external`

This is the high-level class of estimation method.

At the initial stage, at least the following are recommended:

- `lightweight` (`weakscaling`-based minimum path)
- `detailed`
- `external`

### 4.4 detail_level

推定の詳細度である。

初期段階では少なくとも以下を推奨する。

- `basic`
- `intermediate`
- `advanced`

This is the detail level of the estimation.

At the initial stage, at least the following are recommended:

- `basic`
- `intermediate`
- `advanced`

### 4.5 required_inputs

推定に必要な入力集合を定義する。

少なくとも以下を表現できることが望ましい。

- 必須入力一覧
- 任意入力一覧
- 外部入力一覧

`lightweight` class であっても、各システム側のターゲットノード数を推定入力として扱えることが望ましい。ここでいう `lightweight` は、`weakscaling` のような最小構成の区間分割推定を含む。

The metadata defines the required input set for estimation.

It should preferably be able to express at least:

- a list of mandatory inputs
- a list of optional inputs
- a list of external inputs

Even for the `lightweight` class, it should preferably be possible to treat the target node count on each system side as part of the estimation inputs. Here, `lightweight` includes minimum section-wise paths such as `weakscaling`.

### 4.6 fallback_policy

必要入力不足時の扱いを定義する。

初期段階では少なくとも以下を表現できることが望ましい。

- `none`
- `allowed`
- `required`

この項目は、フォールバック先の package 名または方式名を補助的に保持してよい。

This defines how missing required inputs should be handled.

At the initial stage, it should preferably be able to express at least:

- `none`
- `allowed`
- `required`

This field may also hold the target package or method name used for fallback.

## 5. 任意拡張項目 / Optional Extension Fields

推定パッケージ metadata は必要に応じて以下を持ってよい。

- `description`
- `measurement_assumptions`
- `package_origin`
- `package_location`
- `invocation_mode`
- `access_requirements`
- `supported_future_systems`
- `estimate_json_mapping`
- `notes`

Estimation-package metadata may optionally contain:

- `description`
- `measurement_assumptions`
- `package_origin`
- `package_location`
- `invocation_mode`
- `access_requirements`
- `supported_future_systems`
- `estimate_json_mapping`
- `notes`

### 5.1 package_origin

推定パッケージの配置・提供形態を表す。
初期段階では少なくとも以下を表現できることが望ましい。

- `bundled_repository`
- `local_file`
- `external_repository`
- `vendor_provided`
- `external_service`

これは、推定方式の実装本体が BenchKit と同じ公開リポジトリに同梱されるのか、別の公開または非公開リポジトリで管理されるのか、あるいはローカルやベンダー指定の形で扱われるのかを BenchKit から識別するための補助情報である。

Represents how the package is placed or provided.
At the initial stage, it should preferably be able to express at least:

- `bundled_repository`
- `local_file`
- `external_repository`
- `vendor_provided`
- `external_service`

This helps BenchKit identify whether the package implementation is bundled in the same public repository as BenchKit, managed in a separate public or private repository, or handled locally or by vendor-specific means.

### 5.2 package_location

推定パッケージの所在を表す補助情報である。
これはリポジトリ内の相対パスに限らず、ローカルファイルのパス、別の公開または非公開リポジトリの識別子、ベンダー指定の配置識別子、外部サービス名などであってよい。

This is auxiliary information describing where the package is located.
It is not limited to a repository-relative path and may instead be a local file path, an identifier for a separate public or private repository, a vendor-specified placement identifier, or an external service name.

### 5.3 invocation_mode

推定パッケージをどのように呼び出すかを表す補助情報である。
初期段階では少なくとも以下を表現できることが望ましい。

- `source_shell`
- `execute_local_command`
- `vendor_wrapper`
- `call_service`

This is auxiliary information describing how the package is invoked.
At the initial stage, it should preferably be able to express at least:

- `source_shell`
- `execute_local_command`
- `vendor_wrapper`
- `call_service`

### 5.4 access_requirements

推定パッケージの利用に必要な前提条件を表す補助情報である。
例:

- 特定拠点でのみ利用可能
- ベンダー提供モジュールの読み込みが必要
- ローカルファイルの事前配置が必要
- 非公開仕様に基づくため公開リポジトリには格納しない

This is auxiliary information describing prerequisites for using the package.
Examples:

- available only at specific sites
- requires loading vendor-provided modules
- requires prior placement of local files
- not stored in a public repository because it depends on non-public specifications

## 6. 最小例 / Minimum Example

```json
{
  "name": "weakscaling",
  "version": "0.1",
  "method_class": "lightweight",
  "detail_level": "basic",
  "required_inputs": {
    "mandatory": ["result_json", "fom", "target_nodes_current", "target_nodes_future"],
    "optional": ["fom_breakdown"],
    "external": []
  },
  "fallback_policy": {
    "mode": "none",
    "target": null
  }
}
```

## 7. Estimate JSON との関係 / Relationship to Estimate JSON

少なくとも以下の対応関係を持てることが望ましい。

- `name` -> `estimate_metadata.estimation_package`
- `version` -> `estimate_metadata.estimation_package_version`
- `method_class` -> `estimate_metadata.method_class`
- `detail_level` -> `estimate_metadata.detail_level`
- `fallback_policy` と入力判定結果 -> `applicability`

At least the following mappings are desirable:

- `name` -> `estimate_metadata.estimation_package`
- `version` -> `estimate_metadata.estimation_package_version`
- `method_class` -> `estimate_metadata.method_class`
- `detail_level` -> `estimate_metadata.detail_level`
- `fallback_policy` and input-evaluation results -> `applicability`

## 8. 現時点で固定しないもの / Items Not Fixed Yet

本書は以下をまだ固定しない。

- metadata を JSON で持つか shell 変数で持つか
- `required_inputs` の完全体系
- `fallback_policy` の詳細辞書
- package discovery の仕組み
- `package_location` の記法を URI 風にするか単純文字列にするか

This document does not yet fix:

- whether metadata is stored as JSON or shell variables
- the complete taxonomy of `required_inputs`
- the detailed dictionary for `fallback_policy`
- the mechanism for package discovery
- whether `package_location` should use a URI-like syntax or a plain string
