# 推定パッケージ追加手順（開発者向け）

このドキュメントは、BenchKit に新しい推定パッケージを追加する手順を開発者向けにまとめたものです。
軽量パッケージ、上位パッケージ、区間パッケージのどれを作る場合でも、最初に見る実務ガイドとして使うことを想定しています。

## 目次

1. [最初に決めること](#1-最初に決めること)
2. [どこに置くか](#2-どこに置くか)
3. [最低限実装するもの](#3-最低限実装するもの)
4. [section package の考え方](#4-section-package-の考え方)
5. [fallback と not_applicable](#5-fallback-と-not_applicable)
6. [やらなくてよいこと](#6-やらなくてよいこと)
7. [確認ポイント](#7-確認ポイント)
8. [今後の改善](#8-今後の改善)

---

## 1. 最初に決めること

まず次を決めます。

- 上位パッケージか区間パッケージか
- 必要入力は何か
- 不足時に代替へ切り替えられるか
- 何を `bench_time -> time` に変換するか
- どんな assumptions / model / measurement を返すか

最初の package では、欲張らずに

- 1 種類の入力
- 1 つの変換規則
- 1 つの代替方針

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
  `identity.sh`
  `counter_papi_detailed.sh`
  `trace_mpi_basic.sh`
  `logp.sh`
  `overlap_max_basic.sh`

という分け方になっています。

---

## 3. 最低限実装するもの

### 上位パッケージ

少なくとも次があると扱いやすいです。

- メタデータ
- applicability 判定
- run
- metadata の Estimate JSON 反映

### 区間パッケージ

区間パッケージは、もっと小さくてかまいません。
現時点では少なくとも次で十分です。

- メタデータ
- 適用可否判定
- 変換処理

### やることのイメージ

- 入力が足りるか判定する
- 足りれば `bench_time` などから `time` を作る
- 足りなければ代替先を返すか `not_applicable` を返す

---

## 4. 区間パッケージの考え方

区間パッケージは「1 区間の変換規則」と考えると分かりやすいです。

たとえば、

- `identity`
  - 区間時間があれば固定比で変換
- `counter_papi_detailed`
  - PAPI artifact があればそれを前提に変換
- `logp`
  - collective 系の区間を logP 扱いで変換

です。

上位パッケージは、

- section / overlap を集約する
- どの区間パッケージを呼ぶか決める
- 全体の適用可否をまとめる

役割を持ちます。

この分離により、区間パッケージ開発者は 1 区間のルールに集中できます。

---

## 5. 代替と not_applicable

意味は次の通りです。

- `fallback`
  - このパッケージ単体では要求どおり処理できない
  - ただし別のパッケージへ切り替えれば継続できる
- `not_applicable`
  - 代替手段がなく、その項目は成立しない

重要なのは、無理に成功っぽい値を返さないことです。

いまの方針では、

- 代替できない section / overlap は `time: null`
- それを含む全体 FOM も `null`
- top-level は `not_applicable`

となります。

これは後で問題切り分けしやすいので、かなり大事です。

---

## 6. やらなくてよいこと

package 開発者が毎回やらなくてよいことは次です。

- 結果サーバーへの保存
- UUID / timestamp の採番
- ポータル表示
- 全体の Estimate JSON の全面手組み
- 比較画面のことを考えた表示整形

BenchKit 側が引き受けるべきなのは、

- 要求パッケージ / 実適用パッケージの記録
- 全体の適用可否の集約
- 出自情報の保持
- 保存後のポータル表示

です。

package 開発者は、できるだけ

- 必要入力
- 変換規則
- 代替方針

に集中できる形がよいです。

---

## 7. 確認ポイント

### 単体で見るポイント

- metadata が返せる
- applicability が返せる
- 入力不足時に理由が見える
- fallback 先があるなら返せる

### 全体で見るポイント

- 要求パッケージ / 実適用パッケージが分かれる
- 一部区間だけ代替したら `partially_applicable`
- 不成立区間が残ると `not_applicable`
- `null` が最終 FOM まで正しく伝播する

### ポータルで見るポイント

- 要求パッケージ
- 実適用パッケージ
- applicability
- estimate UUID

が最低限見える

---

## 8. 今後の改善

### すでに進んでいること

- 最初の package を 1 本追加すること
- 要求パッケージ / 実適用パッケージを残すこと
- 全体の適用可否を共通で持つこと
- `not_applicable` を `null` 伝播で誠実に表現すること

### 今後の改善

- パッケージメタデータの見つけ方の共通化
- 複数の詳細パッケージ間での代替の共通化
- 区間パッケージのテンプレート化
- ポータル側の詳細表示

## パッケージの入口と出口を先に決める

実装に入る前に、各推定 package について次を 1 回書き出しておくのがよいです。

- どの入力 system の result を受けるか
  - 例: `MiyabiG` のみ、`RC_GH200` のみ、またはその両方
- どの出力先 system を想定するか
  - 例: `FugakuNEXT`
- Result JSON のどの field が必要か
  - 例: `fom`, `fom_breakdown.sections`
- どの区間 artifact が必要か
  - 例: `compute_solver_papi.tgz`, `allreduce_trace.tgz`
- それが無いときどうするか
  - `fallback`
  - `not_applicable`
- 何を出力として埋めるか
  - section `time`
  - `current_system.model`
  - `future_system.model`
  - `applicability`

最小のメモはこれで十分です。

```text
package: counter_papi_detailed
source_system_scope: MiyabiG, RC_GH200
target_system_scope: FugakuNEXT
required_result_fields: fom_breakdown.sections
required_section_artifacts:
  compute_hopping: papi
  compute_solver: papi
output_fields:
  future_system.fom_breakdown.sections[].time
  current_system.fom_breakdown.sections[].time
fallback_to: identity
```

このとき、上位パッケージと区間パッケージで役割を分けておくと整理しやすくなります。
- 上位パッケージ
  - どの区間パッケージ群を使って合成できるか
  - 何を top-level Estimate JSON に出すか
- 区間パッケージ
  - どの system 範囲を受けるか
  - section / overlap のどちらを受けるか
  - どの採取種別を必要とするか
  - 何を出力するか

ここで、上位パッケージは app 固有の section 名を固定で期待しない方がよいです。どの section にどの package を割り当てるかは app 側 Result JSON の `estimation_package` で表します。

`weakscaling` はこの分担を確認する最初の例として分かりやすいです。
- app 側
  - section / overlap 時間を出す
  - 各 item に `identity` または `logp` を割り当てる
- package 側
  - `identity` と `logp` の意味を定義する
  - `weakscaling` として合成する
- BenchKit 側
  - 割当てられた package を呼ぶ
  - current / future の breakdown と top-level FOM をまとめる

PAPI のように複数回の採取が必要な場合でも、package 開発者は「`papi` が必要」と定義するところまでに責務を寄せるのがよいです。どの counter set を何回に分けて取るか、どこへ保存するか、再推定時にどう復元するかは、できるだけ BenchKit 側の共通処理に寄せます。

ここが曖昧なまま実装を始めると、
- package 自体は動く
- でもどの system で使えるのか分からない
- artifact 欠損時の扱いが揺れる
- 比較画面やポータルで意味が読み取りにくい

となりやすいです。

逆にここが最初に決まっていれば、BenchKit 側に寄せるべき共通処理と、package 側で本当に書くべきロジックがかなり分かりやすくなります。

現状の見方としては、

- package を書き始められる土台はある
- 量産しやすい状態まではもう一歩

という整理になります。
