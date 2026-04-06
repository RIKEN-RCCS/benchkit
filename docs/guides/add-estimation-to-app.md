# アプリに性能推定を追加する手順

このドキュメントは、BenchKit の既存アプリに性能推定を追加する手順を開発者向けにまとめたものです。
まずは軽量推定を載せ、その後に section ベースの詳細推定へ広げる流れを前提にしています。

## 目次

1. [最初に何を決めるか](#1-最初に何を決めるか)
2. [最小構成: 軽量推定だけ追加する](#2-最小構成-軽量推定だけ追加する)
3. [詳細推定に広げる](#3-詳細推定に広げる)
4. [`run.sh` でやること](#4-runsh-でやること)
5. [`estimate.sh` でやること](#5-estimatesh-でやること)
6. [artifact の扱い](#6-artifact-の扱い)
7. [確認ポイント](#7-確認ポイント)
8. [いま何が簡単で、何がまだ重いか](#8-いま何が簡単で何がまだ重いか)

---

## 1. 最初に何を決めるか

推定を入れる前に、まず次を決めます。

- 軽量推定だけで始めるか
- section / overlap まで出して詳細推定に進むか
- section ごとにどの推定 package を使いたいか
- 補助 artifact が必要か

最初の一歩としては、軽量推定だけを載せるのが一番簡単です。

---

## 2. 最小構成: 軽量推定だけ追加する

最小構成では、必要なのは次の 2 つです。

1. `run.sh` で FOM を出す
2. `estimate.sh` で `lightweight_fom_scaling` を選ぶ

この段階では、section や artifact は不要です。

### `estimate.sh` の最小イメージ

```bash
#!/bin/bash
set -euo pipefail

BK_ESTIMATION_PACKAGE="lightweight_fom_scaling"
source scripts/estimation/common.sh
source "scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh"

bk_run_estimation "$1"
```

ここで app 側に重いロジックを書かないのがポイントです。

---

## 3. 詳細推定に広げる

詳細推定に進むときは、次の順で広げるのが安全です。

1. `run.sh` で section を出す
2. 必要なら overlap を出す
3. section ごとに `estimation_package` を付ける
4. 必要なら section ごとに `artifacts` を付ける
5. `estimate.sh` で top-level package を詳細型に切り替える

現時点では `qws` が参照例です。

---

## 4. `run.sh` でやること

### 最低限

最低限必要なのは FOM の出力です。

```bash
source "${PWD}/scripts/bk_functions.sh"

mkdir -p results && > results/result

bk_emit_result \
  --fom "$FOM" \
  --fom-version "$FOM_VERSION" \
  --exp "$EXP" \
  --nodes "$nodes" \
  --numproc-node "$numproc_node" \
  --nthreads "$nthreads" >> results/result
```

### 詳細推定まで入れる場合

section / overlap を出す場合は、少なくとも次を意識します。

- 区間名
- 区間時間
- その区間に使いたい推定 package 名
- 必要なら artifact 参照

イメージとしては次のようになります。

```bash
bk_emit_section \
  prepare_rhs 0.42 \
  --estimation-package interval_time_simple \
  --artifact results/estimation_inputs/prepare_rhs_interval.json \
  >> results/result

bk_emit_section \
  compute_solver 1.03 \
  --estimation-package counter_papi_detailed \
  --artifact results/estimation_inputs/compute_solver_papi.tgz \
  >> results/result

bk_emit_overlap \
  compute_hopping,halo_exchange 0.23 \
  --estimation-package overlap_max_basic \
  --artifact results/estimation_inputs/compute_halo_overlap.json \
  >> results/result
```

アプリ側で大事なのは「何を測って何を渡すか」までです。
その解釈や fallback は package 側へ寄せます。

---

## 5. `estimate.sh` でやること

`estimate.sh` は薄い方がよいです。
現時点では、基本的に次だけで済む形を目指します。

- top-level estimation package を選ぶ
- 必要なら app 固有の最小パラメータを設定する
- 共通フローを呼ぶ

避けたいのは、app ごとに

- fallback 制御
- Estimate JSON 手組み
- top-level applicability 判定
- section package dispatch

を書くことです。

### 詳細推定のイメージ

```bash
#!/bin/bash
set -euo pipefail

BK_ESTIMATION_PACKAGE="instrumented_app_sections_dummy"
source scripts/estimation/common.sh
source "scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh"

bk_run_estimation "$1"
```

---

## 6. artifact の扱い

詳細推定では、補助 artifact を app 側で作ることがあります。
典型例は次です。

- interval JSON
- カウンター tgz
- MPI trace tgz
- overlap JSON

置き場所は、まずは `results/estimation_inputs/` に揃えるのが分かりやすいです。

```bash
mkdir -p results/estimation_inputs
```

アプリ側の責務は「採取して置くこと」までです。
その中身の評価や fallback の判断は package 側へ寄せます。

---

## 7. 確認ポイント

### 軽量推定の確認

- `estimate*.json` が生成される
- `estimate_metadata.estimation_package` が `lightweight_fom_scaling`
- `performance_ratio` が出る

### 詳細推定の確認

- `fom_breakdown.sections` が出る
- section ごとの `estimation_package` が残る
- artifact 参照が残る
- `requested_estimation_package` と実適用 package が必要なら分かれる

### fallback の確認

- 一部区間だけ fallback したら top-level `applicability.status = partially_applicable`
- fallback した区間に `requested_estimation_package` と `fallback_used` が残る

### not_applicable の確認

- 不成立区間の `time` が `null`
- top-level `fom` と `performance_ratio` が `null`
- `applicability.status = not_applicable`

---

## 8. いま何が簡単で、何がまだ重いか

### かなり簡単になっていること

- 軽量推定を 1 本載せること
- `estimate.sh` を薄く保つこと
- requested / applied package の記録
- UUID / timestamp の保存
- portal での基本表示

### まだ重いこと

- section の切り方を app 側で設計すること
- artifact をどう採るか決めること
- 詳細推定を `qws` 以外へ横展開すること

つまり現状では、

- 軽量推定の導入負荷は小さい
- 詳細推定は参照実装ができた段階

という理解が近いです。
