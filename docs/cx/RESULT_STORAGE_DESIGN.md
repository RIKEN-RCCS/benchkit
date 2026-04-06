# Result保存設計メモ / Result Storage Design Memo

## 言語方針 / Language Policy

本書は日本語を正本とし、英語は参照用の補助訳とする。
解釈に差異がある場合は日本語版を優先する。

This document uses Japanese as the authoritative version.
The English text is provided as a supporting reference translation.
If any discrepancy exists, the Japanese version takes precedence.

## 1. 文書の位置づけ / Position of This Document

本書は、[`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md) や [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md) を補う保存設計メモである。
本書は仕様を固定する文書ではなく、`results` および `estimated` の保存方法、命名規則、探索性、将来拡張について整理する設計メモである。

This document is a storage-design memo that complements [`BENCHKIT_SPEC.md`](./BENCHKIT_SPEC.md) and [`ESTIMATE_JSON_SPEC.md`](./ESTIMATE_JSON_SPEC.md).
It is not a document that fixes normative specification details.
Instead, it records design considerations for storing `results` and `estimated` data, including naming, discoverability, and future extensibility.

## 2. 基本整理 / Basic Separation

本件は次の 3 層を分けて考えるのがよい。

- 仕様:
  何を識別できなければならないか
- 設計:
  どこにどう置くか
- 実装:
  ファイル名、JSON、manifest、DB、index のどれで実現するか

少なくとも仕様として固定すべきなのは、以下である。

- benchmark result は UUID / timestamp 等で識別できること
- estimate result も UUID / timestamp 等で識別できること
- 各推定側の参照ベンチマークの出自情報と、推定結果自体の出自情報を区別できること

一方で、以下は設計または実装の裁量として残す。

- 結果ファイルをどのディレクトリに置くか
- UUID / timestamp を JSON 内、ファイル名、DB のどこで保持するか
- 補助 index を持つか
- DB を使うかどうか

It is helpful to separate this topic into three layers:

- specification:
  what must be identifiable
- design:
  where and how things are stored
- implementation:
  whether this is realized by filenames, JSON fields, manifests, indexes, or databases

At the specification level, the following should be fixed:

- benchmark results should be identifiable by UUID / timestamp or equivalent identifiers
- estimate results should likewise be identifiable by UUID / timestamp or equivalent identifiers
- side-specific reference-benchmark provenance should be distinguishable from estimate-result provenance

By contrast, the following should remain design or implementation choices:

- which directories hold the files
- whether UUID / timestamp are stored in JSON, filenames, DB records, or all of them
- whether auxiliary indexes are maintained
- whether a database is used

## 3. 現状整理 / Current State

現状では、result および estimate は主としてファイルベースで扱われている。

- Result JSON は `results/result*.json` として生成される
- estimate は `results/estimate_*.json` として生成・保存される
- result server へ送信した後、server 側が払い出した UUID / timestamp が JSON に書き戻される
- estimate 側でも、推定元 result の UUID / timestamp を Estimate JSON に保持できる
- estimate ファイル名自体にも UUID / timestamp を含める運用が存在する

Web 上の論理的な見え方と、result server 側の実ディレクトリ構成は分かれている。

- Web / 利用者視点
  - `/results/...`
  - `/estimated/...`
- result server 側の実保存先
  - `received`
  - `estimated_results`

現状の result server 実装では、`received` および `estimated_results` というサブディレクトリ名は固定であり、
親ディレクトリのみが `BASE_PATH` と `main` / `dev1` などの環境別構成によって切り替わる。
したがって、実際の保存先は概ね以下となる。

- `${BASE_PATH}/main/received`
- `${BASE_PATH}/main/estimated_results`

この対応は現状実装の事実であり、長期的な仕様として固定すべきとは限らない。
将来的に保存設計を見直す場合には、Web 上の論理名と実ディレクトリ名を分離したまま再設計できる余地を残しておくべきである。

したがって現状は、

- JSON 本文
- ファイル名
- result server 側の保存名

の複数の層に識別情報が分散している。

This system is currently primarily file-based.

- Result JSON is produced as `results/result*.json`
- estimates are produced and stored as `results/estimate_*.json`
- after sending to the result server, server-issued UUID / timestamp are written back into JSON
- Estimate JSON can retain the UUID / timestamp of the source result
- estimate filenames may themselves include UUID / timestamp

As a result, identifiers are currently distributed across multiple places:

- JSON payloads
- filenames
- server-side stored filenames

## 4. 現状方式の利点 / Benefits of the Current File-Based Approach

現状方式には少なくとも以下の利点がある。

- SQL や専用 DB を前提にしなくてよい
- CI artifact として自然に扱いやすい
- 人間が結果ファイルを直接確認しやすい
- GitLab / shell-first 運用と相性がよい
- 小規模から中規模の運用では実装負荷が低い

The current approach has at least the following benefits:

- it does not require SQL or a dedicated database
- it fits naturally with CI artifacts
- people can directly inspect result files
- it fits well with GitLab and shell-first operations
- it has low implementation overhead at small to medium scale

## 5. 設計論点 / Design Questions

今後の件数増加や機能追加を考えると、少なくとも以下は設計論点である。

### 5.1 ディレクトリ構成 / Directory Structure

論点:

- `results/` に result と estimate を同居させ続けるか
- result 用と estimate 用で論理的に分けるか
- upload 用 artifact と長期保存用の構成を分けるか

Questions:

- should `results/` continue to hold both result and estimate files
- should result and estimate outputs be separated logically
- should upload artifacts be separated from long-term storage layout

### 5.2 命名規則 / Naming Convention

論点:

- ファイル名に UUID と timestamp を含めるか
- code / exp / system も含めるか
- 人間可読性と一意性のどちらを優先するか

Questions:

- should filenames include UUID and timestamp
- should they also include code / exp / system
- how should human readability be balanced against uniqueness

### 5.3 index の持ち方 / Indexing

論点:

- index を持たずファイル探索だけで十分か
- 軽量な manifest を追加するか
- compare / re-estimation / cleanup 用の index を別途持つか

Questions:

- is plain file scanning sufficient
- should a lightweight manifest be added
- should a separate index be maintained for compare / re-estimation / cleanup

### 5.4 件数増加時の探索性 / Discoverability at Scale

論点:

- 単純な glob や一覧取得で十分か
- 期間、system、code、exp、UUID 単位の検索をどう支えるか
- portal 表示や再推定処理で探索コストが増えないか

Questions:

- whether simple globbing and directory listing remain sufficient
- how to support searches by date, system, code, exp, or UUID
- whether portal and re-estimation workflows will suffer from growing scan costs

### 5.5 compare / re-estimation / cleanup のしやすさ / Ease of Compare, Re-Estimation, and Cleanup

論点:

- 同一 benchmark result に紐づく複数 estimate をどう見つけるか
- 古い estimate や中間 artifact をどう整理するか
- 再推定時に元 result や元 estimate をどう辿るか

Questions:

- how to locate multiple estimates derived from the same benchmark result
- how to manage old estimates and intermediate artifacts
- how to trace back to original results or prior estimates during re-estimation

## 6. 今後の設計候補 / Candidate Directions

本書は単一案を固定しないが、少なくとも以下の方向は検討対象となる。

### 6.1 現状のファイルベース継続 / Continue the Current File-Based Approach

特徴:

- 結果本体は JSON ファイル
- UUID / timestamp は JSON とファイル名の両方に保持してよい
- 必要最小限の shell / portal 改修で済む

向いている場面:

- 件数がまだ限定的
- shell-first を優先したい
- DB 導入コストを避けたい

### 6.2 ファイルベース + 軽量 manifest / File-Based with Lightweight Manifest

特徴:

- JSON 本体はそのまま維持
- 追加で index 用 manifest を持つ
- UUID、timestamp、code、exp、system、source_result_uuid などを索引化する

向いている場面:

- compare や re-estimation が増えてくる
- DB までは不要だが検索性を高めたい

### 6.3 ファイルベース + DB 併用 / File-Based with DB Assistance

特徴:

- JSON ファイルは正本または配布形のまま維持
- DB は索引や検索補助に用いる
- portal や compare 機能は DB を参照して高速化できる

向いている場面:

- 件数や検索要件が増える
- compare / re-estimation / cleanup を運用機能として強めたい

ただし、この方向は SQL や DB を前提とする設計・運用負荷を伴うため、早期に固定すべきではない。

## 7. 当面の方針 / Near-Term Guidance

当面は次の整理が妥当である。

- 仕様では、result / estimate が UUID / timestamp 等で識別可能であることだけを重視する
- 保存場所や命名規則は実装依存として残す
- 現状のファイルベース運用を維持しつつ、必要になれば manifest や index を追加する
- DB 化は件数増加や compare / re-estimation 要件が十分に見えてから判断する

For the near term, the following is a reasonable position:

- at the specification level, emphasize only that result / estimate objects are identifiable by UUID / timestamp or equivalent identifiers
- leave storage location and naming as implementation-dependent
- continue the current file-based approach and add manifests or indexes only when needed
- defer any stronger DB commitment until scale and compare / re-estimation requirements become clearer

## 8. 現時点で固定しないこと / Items Not Fixed Yet

本書は少なくとも以下を現時点では固定しない。

- result / estimate の最終ディレクトリ構成
- estimate ファイル名の最終命名規則
- UUID / timestamp を JSON とファイル名のどちらに必須化するか
- manifest を常設するかどうか
- SQL / DB を将来前提にするかどうか

These items are intentionally left open for now:

- the final directory structure for result / estimate storage
- the final naming convention for estimate files
- whether UUID / timestamp must be mandatory in JSON, filenames, or both
- whether a permanent manifest should exist
- whether SQL / DB should become a future assumption
