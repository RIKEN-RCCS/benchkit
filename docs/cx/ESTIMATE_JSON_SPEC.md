# Estimate JSON 仕様 / Estimate JSON Specification

## 言語方針 / Language Policy

本書は日本語を正本とし、英語は参照用の補助訳とする。
解釈に差異がある場合は日本語版を優先する。

This document uses Japanese as the authoritative version.
The English text is provided as a supporting reference translation.
If any discrepancy exists, the Japanese version takes precedence.

## 1. 文書の位置づけ / Position of This Document

本書は [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md) に対するデータ形式仕様であり、BenchKit が保存・表示・比較する Estimate JSON の最小契約を定義する。

This document is the data-format specification corresponding to [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md), defining the minimum contract for Estimate JSON as stored, presented, and compared by BenchKit.

## 2. 目的 / Purpose

Estimate JSON は、性能推定結果を以下の目的で保持する。

- portal 表示
- 比較
- 履歴追跡
- 再推定
- AI 駆動最適化への受け渡し

Estimate JSON stores estimation results for the following purposes:

- portal presentation
- comparison
- history tracking
- re-estimation
- handoff to AI-driven optimization

## 3. 基本方針 / Basic Policy

Estimate JSON は、次の 2 層構造を基本とする。

1. 最小必須項目
2. 将来拡張可能な任意項目

これにより、現行実装との互換を保ちつつ、将来的な詳細推定や複数ツール連携を受け入れられるようにする。

Estimate JSON follows a two-layer policy:

1. minimum required fields
2. optional future-extensible fields

This preserves compatibility with the current implementation while allowing richer estimation and multiple tool integrations later.

## 4. 最小必須項目 / Minimum Required Fields

Estimate JSON は少なくとも以下を持たなければならない。

- `code`
- `exp`
- `current_system`
- `future_system`
- `performance_ratio`

`current_system` と `future_system` は少なくとも以下を持たなければならない。

- `system`
- `fom`
- `target_nodes`
- `scaling_method`
- `benchmark`

`benchmark` は少なくとも以下を持たなければならない。

- `system`
- `fom`
- `nodes`
- `numproc_node`
- `timestamp`
- `uuid`

Estimate JSON must contain at least:

- `code`
- `exp`
- `current_system`
- `future_system`
- `performance_ratio`

Each of `current_system` and `future_system` must contain at least:

- `system`
- `fom`
- `target_nodes`
- `scaling_method`
- `benchmark`

`benchmark` must contain at least:

- `system`
- `fom`
- `nodes`
- `numproc_node`
- `timestamp`
- `uuid`

## 5. 現行互換の最小例 / Minimum Example Compatible with the Current Implementation

```json
{
  "code": "qws",
  "exp": "CASE0",
  "current_system": {
    "system": "Fugaku",
    "fom": 123.456,
    "target_nodes": "4",
    "scaling_method": "measured",
    "benchmark": {
      "system": "Fugaku",
      "fom": 123.456,
      "nodes": "4",
      "numproc_node": "12",
      "timestamp": "2026-04-03 12:34:56",
      "uuid": "00000000-0000-0000-0000-000000000000"
    }
  },
  "future_system": {
    "system": "FugakuNEXT",
    "fom": 246.912,
    "target_nodes": "4",
    "scaling_method": "scale-mock",
    "benchmark": {
      "system": "MiyabiG",
      "fom": 123.456,
      "nodes": "4",
      "numproc_node": "1",
      "timestamp": "2026-04-03 12:34:56",
      "uuid": "11111111-1111-1111-1111-111111111111"
    }
  },
  "performance_ratio": 0.500
}
```

## 6. 任意拡張項目 / Optional Extension Fields

将来拡張として、Estimate JSON は以下の項目を持ってよい。

- `estimate_metadata`
- `measurement`
- `assumptions`
- `input_artifacts`
- `model`
- `applicability`
- `confidence`
- `notes`

Estimate JSON may include the following extension fields:

- `estimate_metadata`
- `measurement`
- `assumptions`
- `input_artifacts`
- `model`
- `applicability`
- `confidence`
- `notes`

### 6.1 estimate_metadata

推定処理そのものの識別情報を保持する。

想定項目:

- `estimation_id`
- `timestamp`
- `method_class`
- `detail_level`
- `source_result_uuid`
- `estimation_package`
- `estimation_package_version`

例:

```json
{
  "estimate_metadata": {
    "estimation_id": "est-20260403-0001",
    "timestamp": "2026-04-03 13:00:00",
    "method_class": "lightweight",
    "detail_level": "basic",
    "source_result_uuid": "00000000-0000-0000-0000-000000000000",
    "estimation_package": "lightweight_fom_scaling",
    "estimation_package_version": "0.1"
  }
}
```

This field stores identifiers for the estimation process itself.

### 6.2 measurement

推定入力となった計測方法や採取方式を保持する。

想定項目:

- `tool`
- `method`
- `annotation_method`
- `counter_set`
- `interval_timing_method`

例:

```json
{
  "measurement": {
    "tool": "manual-section-timer",
    "method": "section-timing",
    "annotation_method": "app-annotation",
    "counter_set": null,
    "interval_timing_method": "measured"
  }
}
```

This field stores how the measurement inputs used for estimation were obtained.

### 6.3 model

推定モデルの識別情報を保持する。

想定項目:

- `type`
- `name`
- `version`
- `implementation`

例:

```json
{
  "model": {
    "type": "scaling",
    "name": "scale-mock",
    "version": "0.1",
    "implementation": "programs/qws/estimate.sh"
  }
}
```

This field identifies the estimation model.

### 6.4 assumptions

推定時の仮定を保持する。

例:

```json
{
  "assumptions": {
    "future_cpu_speedup": 2.0,
    "network_behavior": "same-as-baseline"
  }
}
```

This field stores assumptions made during estimation.

### 6.5 applicability

推定方式に必要な入力が十分だったか、不足があったか、フォールバックが行われたかを保持する。

想定項目:

- `status`
- `fallback_used`
- `missing_inputs`
- `required_actions`

例:

```json
{
  "applicability": {
    "status": "fallback",
    "fallback_used": "lightweight-fom-only",
    "missing_inputs": [
      "detailed_counters",
      "annotated_interval_timings"
    ],
    "required_actions": [
      "re-measure-with-detailed-counter-tool"
    ]
  }
}
```

This field records whether the requested estimation method had sufficient inputs, whether fallback was used, and what was missing.

### 6.6 confidence

推定結果の信頼度や品質指標を保持する。

例:

```json
{
  "confidence": {
    "level": "experimental",
    "score": 0.55
  }
}
```

This field stores confidence or quality indicators for the estimate.

## 7. FOM breakdown の扱い / Handling of FOM Breakdown

`current_system` および `future_system` は、必要に応じて `fom_breakdown` を持ってよい。

`fom_breakdown` は少なくとも以下の形を想定する。

- `sections`
- `overlaps`

各 section は少なくとも以下を持ってよい。

- `name`
- `bench_time`
- `scaling_method`
- `time`

Each of `current_system` and `future_system` may optionally contain `fom_breakdown`.

`fom_breakdown` is expected to contain at least:

- `sections`
- `overlaps`

Each section may contain at least:

- `name`
- `bench_time`
- `scaling_method`
- `time`

## 8. 将来拡張時の互換性 / Compatibility for Future Extensions

BenchKit は、最小必須項目が満たされていれば、未知の任意項目を原則として破棄せず保持できることが望ましい。

これにより、

- 新しい計測ツール
- 新しい推定モデル
- 新しい AI 連携項目

を段階的に追加しやすくする。

BenchKit should preferably preserve unknown optional fields as long as the minimum required fields are present.

This makes it easier to introduce:

- new measurement tools
- new estimation models
- new AI integration metadata

incrementally over time.

## 9. 現時点で固定しないもの / Items Not Fixed Yet

本書は以下をまだ固定しない。

- `measurement` の具体キー集合
- `model` の詳細 taxonomy
- `applicability.status` の標準値集合
- `confidence` の尺度
- `assumptions` の標準辞書

これらは推定機能の設計・実装が進んだ段階で、実データを見ながら固定する。

This document does not yet fix:

- the complete key set of `measurement`
- the detailed taxonomy of `model`
- the standard value set of `applicability.status`
- the scale for `confidence`
- a standard dictionary for `assumptions`

These should be fixed later based on actual implementation and observed data.
