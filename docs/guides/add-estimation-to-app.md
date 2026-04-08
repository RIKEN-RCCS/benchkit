# アプリに性能推定を追加する

このガイドは、BenchKit の既存アプリに性能推定を追加する開発者向けの実務メモです。

最初に押さえるべき点は次の 2 つです。
- app 側でまず決めるのは、FOM と section / overlap の名前、および各 section / overlap に使う `estimation_package`
- 採取手順、保存形式、再推定時の復元方法は、共通化できるものから BenchKit 側へ寄せる

## 目次

1. [最初に決めること](#1-最初に決めること)
2. [最小構成: 軽量推定だけを追加する](#2-最小構成-軽量推定だけを追加する)
3. [詳細推定に入る](#3-詳細推定に入る)
4. [`estimate.sh` に書くこと](#4-estimatesh-に書くこと)
5. [`run.sh` で書くこと](#5-runsh-で書くこと)
6. [`estimate.sh` を入口として使う](#6-estimatesh-を入口として使う)
7. [採取と保存の扱い](#7-採取と保存の扱い)
8. [確認ポイント](#8-確認ポイント)
9. [今後の改善](#9-今後の改善)

---

## 1. 最初に決めること

アプリに性能推定を入れる前に、まず次を決めます。
- FOM を何にするか
- どの section / overlap を result に出すか
- 各 section / overlap にどの `estimation_package` を割り当てるか

最初の一歩としては、軽量推定から入るのが一番簡単です。

---

## 2. 最小構成: 軽量推定だけを追加する

最小構成では、次の 2 つで十分です。
1. `run.sh` で FOM を出す
2. `estimate.sh` で軽量推定 package を選ぶ

この段階では section や artifact は不要です。

### `estimate.sh` の最小例

```bash
#!/bin/bash
set -euo pipefail

BK_ESTIMATION_PACKAGE="weakscaling"
source scripts/estimation/common.sh
source "scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh"

bk_run_estimation "$1"
```

---

## 3. 詳細推定に入る

詳細推定に入るときは、次の順で進めます。
1. `run.sh` で section を出す
2. 必要なら overlap を出す
3. section / overlap ごとに `estimation_package` を付ける
4. `estimate.sh` で上位 package を詳細側に切り替える

このとき app 側で最初に決めるべきなのは、どの section / overlap にどの推定 package を使うかです。

---

## 4. `estimate.sh` に書くこと

詳細推定では、app ごとの推定宣言を `estimate.sh` にまとめると整理しやすくなります。`estimate.sh` 自身は CI や再推定の入口になり、`run.sh` 側も必要に応じてこれを読み込む形にできます。

`weakscaling` を使う場合は、特に次の分担を前提にすると分かりやすいです。
- app 側
  - section / overlap の時間を通常実行で出す
  - 各 item に `identity` または `logp` を割り当てる
- package 側
  - `identity` は補正なし
  - `logp` は node 数比較にもとづく補正
- BenchKit 側
  - section package の呼び分け
  - current / future の合成
  - top-level applicability の整理

ここでまず宣言したいのは次です。
- section 名
- overlap 名
- 各 section / overlap に割り当てる `estimation_package`
- target system や target nodes の app 既定値

イメージとしては次のようになります。

```bash
bk_declare_section prepare_rhs identity
bk_declare_section compute_solver counter_papi_detailed
bk_declare_section allreduce logp
bk_declare_overlap compute_hopping,halo_exchange overlap_max_basic
```

この宣言は `estimate.sh` にまとめ、`run.sh` 側では package 名を重ねて書かない形が望ましいです。app 側は「どの item にどの package を使うか」を先に決め、実行時には得られた値だけを出す形に寄せます。

この宣言は、実行後に section 値を代入するためのものではなく、「何を推定したいか」を実行前に示すためのものです。

---

## 5. `run.sh` で書くこと

### 最小構成

最小構成で必要なのは FOM の出力です。

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

### 詳細推定に入る場合

詳細推定では、少なくとも次を result に載せます。
- 区間名
- 区間時間
- その区間に使いたい推定 package 名

```bash
bk_emit_declared_section \
  prepare_rhs 0.42 \
  >> results/result

bk_emit_declared_section \
  compute_solver 1.03 \
  results/estimation_inputs/compute_solver_papi.tgz \
  >> results/result

bk_emit_declared_overlap \
  compute_hopping,halo_exchange 0.23 \
  results/estimation_inputs/compute_halo_overlap.json \
  >> results/result
```

さらに整理を進めるなら、section 時間の配分やダミー artifact 作成のような推定専用処理も `estimate.sh` 側の関数へ寄せ、`run.sh` ではその関数を 1 回呼ぶだけにしてよいです。

ここで app 側の主責務は、section 名と `estimation_package` の割当てを明示することです。

通常実行のあとに、必要であれば追加採取用の共通入口を呼ぶ形が自然です。

```bash
. ./estimate.sh

mpiexec ./a.out "$@"

bk_run_estimation_data_collection mpiexec ./a.out "$@"
```

`bk_run_estimation_data_collection` は BenchKit の共通入口です。内部では割り当てられた package や site 側の wrapper に応じて必要な採取を分岐します。PAPI や GPU profiler のように追加実行が必要なものは、ここでまとめて扱う方が app 側が軽くなります。

---

## 6. `estimate.sh` を入口として使う

`estimate.sh` は薄く保つ方がよいです。参照実装では、共通層に処理を寄せたうえで package 選択と最小限の app 固有設定だけを書く形を目指します。

### 詳細推定の例

```bash
#!/bin/bash
set -euo pipefail

BK_ESTIMATION_PACKAGE="instrumented_app_sections_dummy"
source scripts/estimation/common.sh
source "scripts/estimation/packages/${BK_ESTIMATION_PACKAGE}.sh"

bk_run_estimation "$1"
```

---

## 7. 採取と保存の扱い

詳細推定では、区間パッケージが `papi` や `trace` のような採取種別を要求することがあります。

ただし `weakscaling` の場合は、追加採取を前提にしません。app 側が通常実行の中で section / overlap 時間を書き、`identity` と `logp` だけで推定する前提です。

app 側では、まず section 名と `estimation_package` を決めることを優先してください。採取手順、複数回実行の要否、保存先、再推定時の復元方法は、共通化できるものから BenchKit 側へ寄せるのがよいです。

特に PAPI のように複数回実行が必要になる採取は、app 側に細かく書かせすぎると重くなります。package 側は「`papi` が必要」と定義し、BenchKit 側が採取や保存の共通処理を引き受ける形が自然です。

現状の参照実装では `results/estimation_inputs/` を使う例がありますが、これは将来も app 側が細かく書き続けるべきという意味ではありません。

`bk_emit_section` や `bk_emit_overlap` は残してよく、`estimate.sh` 内の宣言と共存できます。宣言は package 割当てを先に示し、`bk_emit_*` は実際に得られた値を Result JSON に流し込む手段として使います。

---

## 8. 確認ポイント

### 軽量推定の確認
- `estimate*.json` が出る
- `estimate_metadata.estimation_package` が期待どおり
- `performance_ratio` が出る

### 詳細推定の確認
- `fom_breakdown.sections` が出る
- section ごとの `estimation_package` が残る
- 必要なら `requested_estimation_package` と実適用 package が分かれる
- 必要なら `estimate_metadata.current_package` と `estimate_metadata.future_package` で両側の package を分けて持てる

### fallback の確認
- 一部区間だけ代替したとき `applicability.status = partially_applicable`
- 代替した区間に `requested_estimation_package` と `fallback_used` が残る

### `not_applicable` の確認
- 不成立の区間は `time: null`
- top-level `fom` と `performance_ratio` は `null`
- `applicability.status = not_applicable`

---

## 9. 今後の改善

すでに進んでいること:
- 軽量推定を 1 本追加すること
- `estimate.sh` を薄く保つこと
- requested / applied package の区別
- UUID / timestamp の保存

今後の改善:
- app 側に書く採取手順をさらに減らすこと
- 詳細推定の採取・保存・復元を BenchKit 側へより集約すること
- 複数アプリへの横展開を進めること
