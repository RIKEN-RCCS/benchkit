# 推定パッケージ追加手順（開発者向け）

このドキュメントは、BenchKit に新しい推定 package を追加する手順を開発者向けにまとめたものです。
軽量 package、top-level package、section package のどれを作る場合でも、最初に見る実務ガイドとして使うことを想定しています。

## 目次

1. [最初に決めること](#1-最初に決めること)
2. [どこに置くか](#2-どこに置くか)
3. [最低限実装するもの](#3-最低限実装するもの)
4. [section package の考え方](#4-section-package-の考え方)
5. [fallback と not_applicable](#5-fallback-と-not_applicable)
6. [やらなくてよいこと](#6-やらなくてよいこと)
7. [確認ポイント](#7-確認ポイント)
8. [いま何が簡単で、何がまだ重いか](#8-いま何が簡単で何がまだ重いか)

---

## 1. 最初に決めること

まず次を決めます。

- top-level package か section package か
- 必要入力は何か
- 不足時に fallback できるか
- 何を `bench_time -> time` に変換するか
- どんな assumptions / model / measurement を返すか

最初の package では、欲張らずに

- 1 種類の入力
- 1 つの変換規則
- 1 つの fallback policy

に絞るのが安全です。

---

## 2. どこに置くか

現時点では、主に次のどちらかに置きます。

- top-level package
  - `scripts/estimation/packages/`
- section package
  - `scripts/estimation/section_packages/`

`qws` の詳細ダミーでは、

- top-level:
  `instrumented_app_sections_dummy.sh`
- section:
  `interval_time_simple.sh`
  `counter_papi_detailed.sh`
  `trace_mpi_basic.sh`
  `trace_collective_logp.sh`
  `overlap_max_basic.sh`

という分け方になっています。

---

## 3. 最低限実装するもの

### top-level package

少なくとも次があると扱いやすいです。

- metadata
- applicability 判定
- run
- metadata の Estimate JSON 反映

### section package

section package は、もっと小さくてかまいません。
現時点では少なくとも次で十分です。

- metadata
- applicability
- transform

### やることのイメージ

- 入力が足りるか判定する
- 足りれば `bench_time` などから `time` を作る
- 足りなければ fallback 先を返すか `not_applicable` を返す

---

## 4. section package の考え方

section package は「1 区間の変換規則」と考えると分かりやすいです。

たとえば、

- `interval_time_simple`
  - 区間時間があれば固定比で変換
- `counter_papi_detailed`
  - PAPI artifact があればそれを前提に変換
- `trace_collective_logp`
  - collective 系の区間を logP 扱いで変換

です。

top-level package は、

- section / overlap を集約する
- どの section package を呼ぶか決める
- top-level applicability をまとめる

役割を持ちます。

この分離により、section package 開発者は 1 区間のルールに集中できます。

---

## 5. fallback と not_applicable

意味は次の通りです。

- `fallback`
  - この package 単体では要求どおり処理できない
  - ただし別 package へ切り替えれば継続できる
- `not_applicable`
  - 代替手段がなく、その項目は成立しない

重要なのは、無理に成功っぽい値を返さないことです。

いまの方針では、

- fallback できない section / overlap は `time: null`
- それを含む全体 FOM も `null`
- top-level は `not_applicable`

となります。

これは後で問題切り分けしやすいので、かなり大事です。

---

## 6. やらなくてよいこと

package 開発者が毎回やらなくてよいことは次です。

- result server への保存
- UUID / timestamp の採番
- portal 表示
- top-level Estimate JSON の全面手組み
- compare UI のことを考えた表示整形

BenchKit 側が引き受けるべきなのは、

- requested / applied package の記録
- top-level applicability の集約
- provenance の保持
- 保存後の portal 表示

です。

package 開発者は、できるだけ

- 必要入力
- 変換規則
- fallback policy

に集中できる形がよいです。

---

## 7. 確認ポイント

### 単体で見るポイント

- metadata が返せる
- applicability が返せる
- 入力不足時に理由が見える
- fallback 先があるなら返せる

### top-level で見るポイント

- requested / applied package が分かれる
- 一部区間だけ fallback したら `partially_applicable`
- 不成立区間が残ると `not_applicable`
- `null` が最終 FOM まで正しく伝播する

### portal で見るポイント

- requested package
- applied package
- applicability
- estimate UUID

が最低限見える

---

## 8. いま何が簡単で、何がまだ重いか

### かなり簡単になっていること

- 最初の package を 1 本追加すること
- requested / applied package を残すこと
- top-level applicability を共通で持つこと
- `not_applicable` を `null` 伝播で誠実に表現すること

### まだ重いこと

- package metadata の discovery
- 複数 detailed package 間 fallback の共通化
- section package のテンプレート化
- portal 側の詳細表示

つまり現状では、

- package を書き始められる土台はある
- 量産しやすい状態まではもう一歩

という整理になります。
