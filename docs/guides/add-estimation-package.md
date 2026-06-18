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

この配置は現時点の約束です。将来、推定 package が増えた場合にディレクトリ名や登録方法を見直す可能性があります。
そのため、package 固有のロジック、metadata、applicability 判定はこの配下に閉じ、BenchKit 共通層へ app 固有・package 固有の処理を混ぜないようにしてください。

`qws` の詳細ダミー推定では、たとえば次のような分担です。

- top-level
  - `instrumented_app_sections_dummy.sh`
- section / overlap
  - `identity.sh`
  - `logp.sh`
  - `counter_papi_detailed.sh`
  - `trace_mpi_basic.sh`
  - `overlap_max_basic.sh`
  - `gpu_kernel_lightgbm_v10.sh`
  - `gpu_kernel_mlp_v15.sh`

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

GPU kernel 単位の外部推定ツールは、通常は section package として扱います。
たとえば次の package は、PerfTools の各モデルを「GPU 区間だけを変換する package」として接続します。

- `gpu_kernel_mlp_v15`
  - PerfTools `MLP_NN/v1.5`
  - 主な依存: numpy/pandas/torch
- `gpu_kernel_lightgbm_v10`
  - PerfTools `LightGBM_model/1.0`
  - 主な依存: numpy/pandas/lightgbm/pyyaml と `libgomp`

top-level package は `instrumented_app_sections_dummy` などのままにして、GPU 区間にだけ GPU kernel section package を割り当てます。
どの section package を既定で使うかは app 側の bring-up 状況や CI runner/container に依存するため、このガイドでは特定の package を正解として固定しません。
新しい package を追加した場合は、この一覧と app 側の切り替え変数から選択肢として見えるようにしてください。

```bash
gpu_section_package="${BK_GENESIS_GPU_SECTION_PACKAGE:-gpu_kernel_lightgbm_v10}"
bk_declare_section --side future pairlist "$gpu_section_package"
bk_declare_section --side future pme_real "$gpu_section_package"
bk_emit_declared_section --side future pairlist "$measured_pairlist_time" results/padata0.tgz
bk_emit_declared_section --side future pme_real "$measured_pme_real_time" results/padata0.tgz
```

GENESIS の GPU kernel section package は `BK_GENESIS_GPU_SECTION_PACKAGE` で単発指定できます。
複数の推定 package を比較したい場合は、`BK_GENESIS_GPU_SECTION_PACKAGES` にカンマ区切りで指定します。
複数指定時は `gpu_kernel_ensemble_average` wrapper package が同じ GPU section に対して各 package を実行し、候補結果を同一 Estimate JSON の `candidate_estimates` に保持します。
GENESIS の既定の推定設定では `current_system=Fugaku`、`future_system=FugakuNEXT` として扱います。
GENESIS の FOM はログ上の `dynamics` 時間で、現時点では `pairlist`, `bond`, `angle`, `dihedral`, `pme_real`, `pme_recip`, `integrator` の7区間をログ値のまま登録し、取り切れていない差分を `other` として追加して `dynamics` を再構成します。
このうち `pairlist` と `pme_real` は GPU kernel section package の候補に紐づき、その他の区間と `other` は当面 `identity` です。
NCU 由来の GPU kernel profile は通常アプリ全体の一部の kernel launch だけを含むため、その合計時間を直接 FOM 合成には使いません。
各 GPU package は kernel sample の `predicted/source` 時間比を計算し、その比をアプリ側で採取した GPU section time に掛けて section time を作ります。
FOM 合成に使う section time は、当面は適用できた候補 package の投影後 section time の平均値です。
これにより、将来 CPU/GPU/通信の各 section package を同じ JSON 内で合成しつつ、GPU estimator だけを複数候補として比較できます。
アプリ側 GPU section time が未取得の場合、GPU kernel estimator は FOM 合成には使えず、まずアプリログ、NVTX、または別のアプリ側計時で掛け先となる section time を用意する必要があります。
未指定時の既定値は接続確認中の実装に合わせて変わることがあるため、検証や再現性が必要な場合は明示してください。

```bash
export BK_GENESIS_GPU_SECTION_PACKAGE=gpu_kernel_mlp_v15
# or
export BK_GENESIS_GPU_SECTION_PACKAGE=gpu_kernel_lightgbm_v10
# or compare multiple packages from the same GENESIS result
export BK_GENESIS_GPU_SECTION_PACKAGES=gpu_kernel_lightgbm_v10,gpu_kernel_mlp_v15
```

PerfTools 本体は BenchKit に vendoring せず、実行時に次の環境変数で渡します。

```bash
export BK_GPU_MLP_PERFTOOLS_ROOT=/path/to/PerfTools
export BK_GPU_MLP_PYTHON=python3.11
# LightGBM package だけを明示したい場合
export BK_GPU_LIGHTGBM_PERFTOOLS_ROOT=/path/to/PerfTools
export BK_GPU_LIGHTGBM_PYTHON=python3.11
```

section artifact は PerfTools 側の static GPU spec sheet から作られた prepared CSV を想定します。
BenchKit 実行時に GPU spec を動的採取しません。
テストやデバッグでは、既に作成済みの prediction CSV を使えます。

```bash
export BK_GPU_MLP_ARTIFACT_MODE=prediction
# or section-specific override:
export BK_GPU_MLP_PREDICTION_CSV_GPU_KERNEL_REGION=/path/to/pred.csv
```

section package は prediction CSV の推定実行時間を合算し、その section の future-side `time` にします。
MLP package は `Execution Time [ns]`、LightGBM package は `O-Execution Time` を主な入力列として扱います。
prepared input CSV から source-side の kernel 実測時間を読める場合は、Estimate JSON の metrics に `source_time_ns`, `predicted_time_ns`, `time_ratio_predicted_over_source`, `speedup_factor_source_over_predicted` を出します。
`ncu` の採取 window はアプリ全体の GPU 区間時間ではなく限定された kernel sample なので、実運用ではこの source/target 比を、profiler overhead のないアプリ区間 timing に掛けて FOM を再構築する想定です。

qws を使って CI 配管だけを確認する場合は、実際の qws が GPU 化されていなくても GPU MLP smoke test を有効にできます。
`BK_QWS_GPU_MLP_SMOKE_MODE=prediction` では、同梱のサンプル prediction CSV を使い、run job が `gpu_kernel_region` section と prediction CSV artifact を結果に埋め込みます。
`BK_QWS_GPU_MLP_SMOKE_MODE=perftools` では、estimate job が PerfTools repo を checkout し、`MLP_NN/examples/example_input_mixed-src_20kernels.csv` を `predict_v15.py` に渡して prediction CSV を生成します。
どちらのモードでも、estimate job が `gpu_kernel_mlp_v15` section package を通して Estimate JSON へ変換できることを確認します。
LightGBM など別の GPU kernel section package は、GENESIS の `BK_GENESIS_GPU_SECTION_PACKAGE` のように app 側の切り替え変数や専用テストで確認します。
qws の推定スクリプト単体では既定無効ですが、GPU estimator integration の立ち上げ期間中は GitLab CI 側の既定を一時的に有効化しています。

```bash
export BK_QWS_GPU_MLP_SMOKE=true
export BK_QWS_GPU_MLP_SMOKE_MODE=perftools
export BK_ESTIMATE_RUNNER_TAG=<python-and-jq-estimator-runner-tag>
export BK_GPU_MLP_PERFTOOLS_REPO=https://github.com/masaaki-kondo/PerfTools.git
export BK_GPU_MLP_PERFTOOLS_REF=main
```

これらの変数は、GPU estimator integration の立ち上げ期間だけの暫定スイッチです。
`BK_QWS_GPU_MLP_SMOKE` は qws を使った配管確認用、`BK_QWS_GPU_MLP_SMOKE_MODE` は prediction fixture 取り込みと PerfTools 実行の切り替え用、`BK_ESTIMATE_RUNNER_TAG` は推定用 runner/container を手動で逃がすためのものです。
実際の GPU profiling input と推定 runner の運用が固まったら、専用の package/runner 設定へ置き換え、これらの暫定変数は削除対象として見直してください。

`perftools` smoke mode は GitHub から PerfTools を取得するため、推定 runner/container には `git` と外部接続が必要です。
Python とライブラリは、選択した PerfTools モデル側の要件に合わせます。
Result Server/portal の runtime は Python 3.12 以上ですが、GPU estimator runner は外部推定ツールの runtime です。
MLP package には Python 3.11 以上と numpy/pandas/torch、LightGBM package には Python 3.11 以上と numpy/pandas/lightgbm/pyyaml、さらに LightGBM 実行用の `libgomp` が必要です。
`python3` が 3.10 など古い環境では、`BK_GPU_MLP_PYTHON` や `BK_GPU_LIGHTGBM_PYTHON` に 3.11 以上の interpreter を明示してください。
実運用では smoke mode ではなく、推定 runner/container に PerfTools checkout を用意し、section artifact として実アプリ由来の prepared input CSV を渡してください。

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
- portal の detail や、将来の compare UI で意味が読める

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
