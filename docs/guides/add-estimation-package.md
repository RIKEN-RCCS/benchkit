# 推定パッケージ追加手順（開発者向け）

このドキュメントは、BenchKit に新しい推定 package を追加する開発者向けガイドです。
現在の実装では、package は「推定ロジックと package 固有 metadata を持つ側」、BenchKit 共通層は「flow と JSON 受け渡しを持つ側」として考えると整理しやすいです。

## 1. 最初に決めること

新しい package を書き始める前に、まず次を決めます。

- top-level package か section / overlap package か
- 何を入力として受け取るか
- 入力不足時に fallback できるか
- 何を `bench_time -> time` に変換するか
- どの assumptions / model / measurement を返したいか

最初の package では、欲張らずに

- 1 種類の入力
- 1 つの変換規則
- 1 つの applicability 方針

から始めるのがおすすめです。

## 2. どこに置くか

現在の実装では、主に次に分かれます。

- top-level package
  - `scripts/estimation/packages/`
- section package
  - `scripts/estimation/section_packages/`

`qws` の詳細ダミー推定では、たとえば次のような分担です。

- top-level
  - `instrumented_app_sections_dummy.sh`
- section / overlap
  - `identity.sh`
  - `logp.sh`
  - `counter_papi_detailed.sh`
  - `trace_mpi_basic.sh`
  - `overlap_max_basic.sh`

## 3. top-level package の責務

top-level package は、主に次を担当します。

- metadata を返す
- applicability を判定する
- breakdown 全体を変換する
- top-level FOM を組み立てる
- side ごとの model 情報を返す

少なくとも、`weakscaling` や `instrumented_app_sections_dummy` のような top-level package では、`section` / `overlap` ごとの bound package をどう dispatch するかを意識します。

## 4. section / overlap package の責務

section package はもっと小さくてかまいません。
主に次を返せれば十分です。

- metadata
- applicability
- 1 区間の変換結果

ここでは「1 区間の変換規則」に集中し、Estimate JSON 全体の組み立てや current / future の side 管理は BenchKit 共通層や top-level package 側へ寄せる方が自然です。

## 5. metadata に持たせるもの

現在の実装では、package metadata がかなり重要です。
少なくとも top-level package では、次を metadata に持たせる前提で考えると整理しやすいです。

- `name`
- `version`
- `method_class`
- `detail_level`
- `required_inputs`
- `required_result_fields`
- `supported_section_packages`
- `supported_overlap_packages`
- `output_fields`
- `not_applicable_when`
- `fallback_policy`
- `models`
- `defaults`

特に `models` には、必要に応じて次を持たせます。

- `top_level`
- `current_system`
- `future_system`
- `recorded_current`

また `defaults` には、少なくとも次を持たせると共通層に寄せやすいです。

- `defaults.measurement`
- `defaults.confidence`
- `defaults.notes`
- `defaults.assumptions`

BenchKit 共通層は、これらを読んで Estimate JSON に写像する役割を主に持ちます。

## 6. package 側に持たせるべきもの

package 側で持つべきなのは、主に次です。

- 推定ロジックそのもの
- 必要入力と不足条件
- fallback / not_applicable の方針
- model 名や model type などの package 固有 metadata
- assumptions / measurement / confidence / notes の package 固有既定値

逆に、package 側が毎回持たなくてよいのは次です。

- Estimate JSON 全体の手組み
- requested / applied package の記録
- current / future の side ごとの JSON 組み立て
- UUID / timestamp の保存
- 保存後の portal 表示

## 7. app 固有 section 名をどこまで見るか

top-level package が app 固有の section 名まで固定前提で持ちすぎるのは避けた方がよいです。
section 名そのものより、

- bound package があるか
- 必要 artifact があるか
- fallback 先があるか
- system relation が成立するか

を主に見る形の方が、他 app へ横展開しやすくなります。

`instrumented_app_sections_dummy` でも、現在は固定 section 名そのものを前提にせず、bound package や必要入力の成立を主に見る方向へ寄せています。

## 8. fallback と not_applicable

実装時には、少なくとも次を明示できるとよいです。

- `fallback`
  - この package では直接扱えないが、より軽い package へ落とせる
- `not_applicable`
  - 必要入力や system relation が満たせず、推定を返すべきでない

特に fallback を使うときは、

- 最初に要求された package
- 実際に適用した package
- なぜ切り替えたか

が Estimate JSON や portal 側で追えることが重要です。

## 9. 確認ポイント

### 単体で見るポイント

- metadata が返せる
- applicability が返せる
- 入力不足時に理由が見える
- fallback 先があるなら返せる

### 全体で見るポイント

- requested / applied package が残る
- current / future package が必要なら分かれる
- model 情報が side ごとに残る
- `applicability` が top-level に集約される
- portal や compare UI で意味が読める

## 10. いまの見方

現状の BenchKit では、package を書き始める土台はかなり整っています。

- package metadata を共通層へ写像する流れがある
- current / future package を分けられる
- `current_system.model` / `future_system.model` を side ごとに持てる
- requested / applied package や fallback 理由を残せる
- portal の estimated detail では section / overlap 単位の fallback / applicability まで追える

一方で、まだ未完なのは次です。

- package metadata discovery の一般化
- 複数 detailed package の本格実装
- compare UI での package 差分の見せ方
- reestimation や compare と package metadata をどう結び付けるか

そのため、最初の package では「小さく動かして、metadata と責務分担を崩さない」ことを優先するのがよいです。
