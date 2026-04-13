# Estimate JSON 仕様 / Estimate JSON Specification

## 言語方針 / Language Policy

本書は日本語を正本とし、英語は参照用の補助訳とする。
解釈に差異がある場合は日本語版を優先する。

This document uses Japanese as the authoritative version.
The English text is provided as a supporting reference translation.
If any discrepancy exists, the Japanese version takes precedence.

## 1. 文書の位置づけ / Position of This Document

本書は [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md) に対するデータ形式仕様であり、BenchKit が保存・表示し、将来の比較や再推定にも使えるように保持する Estimate JSON の最小要件を定義する。

This document is the data-format specification corresponding to [`ESTIMATION_SPEC.md`](./ESTIMATION_SPEC.md), defining the minimum requirements for Estimate JSON as stored, presented, and preserved by BenchKit so that future comparison and re-estimation remain possible.

## 2. 目的 / Purpose

Estimate JSON は、性能推定結果を以下の目的で保持する。

- portal 表示
- 比較可能性の保持
- 履歴追跡
- 再推定
- AI 駆動最適化への受け渡し

Estimate JSON stores estimation results for the following purposes:

- portal presentation
- preserving comparability
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

必要に応じて、`current_system` と `future_system` はそれぞれ側ごとの推定モデル情報を `model` として持ってよい。

`benchmark` は少なくとも以下を持たなければならない。

- `system`
- `fom`
- `nodes`
- `numproc_node`
- `timestamp`
- `uuid`

`current_system.benchmark` および `future_system.benchmark` は、それぞれの推定側における基準 benchmark result を表す。
これらは原則として少ノードで実行された実測結果を想定する。
`future_system.benchmark` は将来システムそのものの実測でなくてもよいが、少なくとも将来システムに近い現行アーキテクチャ上での実測結果、または同等の比較基準であることが望ましい。

また、`target_nodes` は各システム側の推定先ノード数を表し、原則としてウィークスケーリング前提で解釈する。

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

`current_system.benchmark` および `future_system.benchmark` は、それぞれの推定側における基準ベンチマーク結果を表す。意味としては、各推定側の参照ベンチマーク（reference benchmark）を指す。
`current_system.benchmark` は current 側推定の基準に用いた参照ベンチマークであり、`future_system.benchmark` は future 側推定の基準に用いた参照ベンチマークである。
これらは必ずしも各側の対象システム自身で直接測定されたベンチマークを意味しない。
現行実装との互換性のため、当面フィールド名は `benchmark` を維持する。ただし意味としては参照ベンチマークであり、将来的にはより明確な名称へ移行してよい。

`current_system.benchmark` and `future_system.benchmark` represent the baseline benchmark result for each estimation side.
Semantically, these fields should be interpreted as side-specific `reference_benchmark`.
These are expected, in principle, to be measured results obtained at small node counts.
`future_system.benchmark` does not have to be a direct measurement on the future system itself, but should preferably be at least a measured result obtained on a current architecture close to the future system, or an equivalent comparison baseline.

That is:

- `current_system.benchmark`
  - the reference benchmark used as the baseline for current-side estimation
- `future_system.benchmark`
  - the reference benchmark used as the baseline for future-side estimation

They do not necessarily mean a benchmark directly measured on the target system of that side.

For compatibility with the current implementation, the field name remains `benchmark` for now.
However, its meaning is effectively `reference_benchmark`, and it may later migrate to a clearer name.

In addition, `target_nodes` represents the estimated node count on each system side and is interpreted, in principle, under a weak-scaling assumption.

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
- `estimation_result_uuid`
- `estimation_result_timestamp`
- `method_class`
- `detail_level`
- `source_result_uuid`
- `estimation_package`
- `estimation_package_version`
- `requested_estimation_package`
- `requested_estimation_package_version`

例:

```json
{
  "estimate_metadata": {
    "estimation_id": "est-20260403-0001",
    "timestamp": "2026-04-03 13:00:00",
    "estimation_result_uuid": "22222222-2222-2222-2222-222222222222",
    "estimation_result_timestamp": "2026-04-03 13:00:00",
    "method_class": "detailed",
    "detail_level": "intermediate",
    "source_result_uuid": "00000000-0000-0000-0000-000000000000",
    "estimation_package": "instrumented_app_sections_dummy",
    "estimation_package_version": "0.1",
    "requested_estimation_package": "instrumented_app_sections_dummy",
    "requested_estimation_package_version": "0.1",
    "current_package": {
      "estimation_package": "weakscaling",
      "estimation_package_version": "0.1",
      "requested_estimation_package": "weakscaling",
      "requested_estimation_package_version": "0.1"
    },
    "future_package": {
      "estimation_package": "instrumented_app_sections_dummy",
      "estimation_package_version": "0.1",
      "requested_estimation_package": "instrumented_app_sections_dummy",
      "requested_estimation_package_version": "0.1"
    }
  }
}
```

この項目は、推定処理そのものに関する識別情報を保持する。
`source_result_uuid` は推定入力として用いたベンチマーク結果を識別する。
`estimation_result_uuid` および `estimation_result_timestamp` は、保存対象としての推定結果そのものの出自情報を識別する。

This field stores identifiers for the estimation process itself.
`source_result_uuid` identifies the benchmark result used as estimation input.
`estimation_result_uuid` and `estimation_result_timestamp` identify the estimate result itself as a stored object.
`estimation_package` と `estimation_package_version` は、実際に適用された推定パッケージを表す。
`requested_estimation_package` と `requested_estimation_package_version` は、フォールバック前に最初に要求された推定パッケージを表す。
`estimation_package` and `estimation_package_version` identify the package that was actually applied.
`requested_estimation_package` and `requested_estimation_package_version` identify the package initially requested before any fallback.

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

単一の top-level `model` は、Estimate JSON 全体を代表する主要モデル、複合モデル、または代表的モデルを表してよい。
これに加えて、`current_system.model` と `future_system.model` を用いて、各システム側に個別の推定モデル情報を保持してよい。

たとえば `current_system.model` には `intra_system_scaling_model` または `cross_system_projection_model` を保持してよく、`future_system.model` にも同様に適切な側モデルを保持してよい。

The single top-level `model` may represent the primary model, a composite model, or the representative model for the entire Estimate JSON.
In addition, `current_system.model` and `future_system.model` may retain side-specific model information.

For example, `current_system.model` may retain either an `intra_system_scaling_model` or a `cross_system_projection_model`, and `future_system.model` may likewise retain whichever side model is appropriate.

必要に応じて、側ごとの `model` は `source_system`、`target_system`、`system_compatibility_rule` を持ってよい。

When needed, a side-specific `model` may contain `source_system`, `target_system`, and `system_compatibility_rule`.

### 6.4 assumptions

推定時の仮定を保持する。

この項目には、少なくとも以下のような仮定を保持してよい。

- ウィークスケーリング前提
- 将来システム仮定
- 通信成分補正の有無
- problem size の増やし方

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

This field may include assumptions such as:

- weak-scaling assumption
- future-system assumption
- whether a communication-cost adjustment is applied
- how problem size is increased

### 6.5 applicability

推定方式に必要な入力が十分だったか、不足があったか、フォールバックが行われたかを保持する。

想定項目:

- `status`
- `fallback_used`
- `missing_inputs`
- `required_actions`
- `incompatibilities`

例:

```json
{
  "applicability": {
    "status": "fallback",
    "fallback_used": "weakscaling",
    "missing_inputs": [
      "detailed_counters",
      "annotated_interval_timings"
    ],
    "required_actions": [
      "re-measure-with-detailed-counter-tool"
    ],
    "incompatibilities": []
  }
}
```

フォールバックが行われた場合、`applicability` には、要求されたパッケージをそのまま適用できなかった理由を記録できることが望ましい。
その場合、`estimate_metadata.requested_estimation_package` は最初に要求されたパッケージを、`estimate_metadata.estimation_package` は実際に適用されたパッケージを表す。
また、`applicability.status` は Estimate JSON の最終状態を表す値として扱う。
少なくとも以下の 4 値を標準値として扱う。

- `applicable`
  - 要求された推定パッケージで、そのまま推定が成立した
- `partially_applicable`
  - 推定全体は成立したが、一部の section / overlap / component でフォールバックが行われた
- `fallback`
  - 要求された top-level 推定パッケージでは成立せず、別の top-level パッケージへ切り替えて推定が成立した
- `not_applicable`
  - 推定は試みられたが、最終的に推定結果として成立しなかった

`not_applicable` はパイプライン失敗を意味しない。
BenchKit は、推定不成立であっても、その試行結果を Estimate JSON として保存・表示してよい。

When fallback occurs, `applicability` should preferably record why the requested package could not be applied.
In such a case, `estimate_metadata.requested_estimation_package` identifies the originally requested package, while `estimate_metadata.estimation_package` identifies the package actually applied.

This field records the final applicability state of the estimate, whether fallback was used, and what was missing.

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
- `estimation_package`
- `artifacts`

Each of `current_system` and `future_system` may optionally contain `fom_breakdown`.

`fom_breakdown` is expected to contain at least:

- `sections`
- `overlaps`

Each section may contain at least:

- `name`
- `bench_time`
- `scaling_method`
- `time`
- `estimation_package`
- `artifacts`

`current_system.fom_breakdown` と `future_system.fom_breakdown` は、同じ section 名、同じ overlap 名、同じ粒度を要求しない。
現行側 baseline の計測時点と、将来側推定のための計測時点でコードや区間分割が異なっていてよい。
したがって、両側の breakdown は 1 対 1 対応の比較表ではなく、それぞれの推定側を説明する補助情報として扱う。

`current_system.fom_breakdown` and `future_system.fom_breakdown` do not have to share the same section names, overlap names, or granularity.
The code version or section partitioning may legitimately differ between the current-side baseline measurement and the future-side estimation input.
Accordingly, the two breakdowns should be treated as side-specific explanatory information rather than as a mandatory one-to-one comparison table.

ここで、

- `bench_time`
  - その section に対する入力基準時間を表す
  - 写像前、補正前、または推定前の時間として解釈する
- `time`
  - その section に対する推定後の時間を表す
  - target system、target nodes、または推定後条件に対応する時間として解釈する

This means:

- `bench_time`
  - represents the input baseline time for that section
  - is interpreted as the pre-mapping, pre-adjustment, or pre-estimation time
- `time`
  - represents the estimated time for that section
  - is interpreted as the time corresponding to the target system, target nodes, or post-estimation condition

### 7.0.1 section ごとの推定部品と補助データ / Section-Wise Estimation Components and Auxiliary Data

各 section は、必要に応じてその区間に適用する推定パッケージ名を `estimation_package` として保持してよい。
また、ハードウェアカウンターの生データ、トレース、区間別ログ、tgz アーカイブなどの補助データ参照を `artifacts` として保持してよい。

`artifacts` は少なくとも以下のような項目を持ってよい。

- `type`
- `path`
- `description`

例:

```json
{
  "name": "compute_cpu_measure_atom_mass",
  "bench_time": 0.30,
  "scaling_method": "measured",
  "time": 0.30,
  "estimation_package": "counter_papi_detailed",
  "artifacts": [
    {
      "type": "hardware_counter_archive",
      "path": "results/papi_compute_cpu_measure_atom_mass.tgz",
      "description": "Raw PAPI counters for this section"
    }
  ]
}
```

Each section may optionally retain the estimation package applied to that section as `estimation_package`.
It may also retain auxiliary data references such as raw hardware-counter data, traces, section-wise logs, or tgz archives as `artifacts`.

`artifacts` may contain at least:

- `type`
- `path`
- `description`

### 7.1 overlaps の意味 / Meaning of overlaps

`overlaps` は、少なくとも二つ以上の `sections` が同時進行しうる区間を表してよい。
各 overlap は少なくとも以下を持ってよい。

- `sections`
- `bench_time`
- `scaling_method`
- `time`

ここで `sections` は、当該 overlap に関与する section 名の配列である。
初期段階では、overlap の意味は「section の単純和から差し引くべき二重計上分」として扱ってよいが、将来的には overlap 自体を独立した区間推定対象として扱ってよい。

`overlaps` may represent regions in which at least two or more `sections` may progress simultaneously.
Each overlap may contain at least:

- `sections`
- `bench_time`
- `scaling_method`
- `time`

overlap についても、`bench_time` は入力基準 overlap 時間、`time` は推定後 overlap 時間として同様に解釈する。

The same interpretation applies to overlap:
`bench_time` is the baseline overlap time, and `time` is the estimated overlap time.

Here, `sections` is an array of section names involved in the overlap.
At the initial stage, overlap may be treated as the double-counted portion to subtract from the simple sum of sections, but in the future overlap itself may be treated as an independent estimable region.

## 7.3 `bench_time` / `time` の名称について / On the Naming of `bench_time` / `time`

現時点では既存実装との互換性を優先して `bench_time` と `time` を用いる。
ただし、これらの意味は単なる benchmark time と time ではなく、実際には「入力基準時間」と「推定後時間」である。

したがって将来的には、必要に応じて次のようなより分かりやすい名称へ移行してよい。

- `baseline_time`
- `estimated_time`

この移行は後方互換性を考慮しながら段階的に行うべきである。

現行実装との互換性のため、当面は `bench_time` と `time` を維持する。
ただし実際の意味は単なるベンチマーク時間と時間ではなく、入力基準時間と推定後時間である。

For compatibility with the current implementation, `bench_time` and `time` are retained for now.
However, their actual meanings are not merely benchmark time and time, but rather baseline input time and estimated time.

Therefore, in the future they may be migrated, when appropriate, to clearer names such as:

- `baseline_time`
- `estimated_time`

Such migration should be performed gradually with backward compatibility in mind.

### 7.2 overlap の参照手法 / Reference Method for Overlap

初期段階のもっとも単純な参照手法としては、関連する section 時間から `max(section_A, section_B, ...)` を用いる近似を許容してよい。
ただし、より詳細な推定方式では、トレース、カウンター、あるいは overlap 区間自体の実測時間を用いてよい。

As the simplest reference method at the initial stage, an approximation based on `max(section_A, section_B, ...)` may be allowed.
However, more detailed estimation methods may instead use traces, counters, or measured timings of the overlap region itself.

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
- `model` の詳細体系
- `confidence` の尺度
- `assumptions` の標準辞書
- section / overlap category の標準語彙
- section ごとの `artifacts` の内部構造

これらは推定機能の設計・実装が進んだ段階で、実データを見ながら固定する。

This document does not yet fix:

- the complete key set of `measurement`
- the detailed taxonomy of `model`
- the scale for `confidence`
- a standard dictionary for `assumptions`
- a standard vocabulary for section / overlap categories
- the internal schema of per-section `artifacts`

These should be fixed later based on actual implementation and observed data.
