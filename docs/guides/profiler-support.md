# Profiler Support Guide

このドキュメントは、BenchKit で profiler を使うときの共通 helper 設計をまとめたものです。

## Language Policy

本書は日本語を正本とし、必要に応じて英語の補助説明を加える。

## 1. 基本方針

BenchKit では、アプリ側が

- profiler tool
- profiler level
- report の必要度

を決め、共通 helper `bk_profiler` が

- 計測実行
- raw data 回収
- postprocess report 作成
- archive 化
- `meta.json` 付与

を担当する。

つまり、アプリ側は「何を使うか」を決め、BenchKit 共通層は「どうまとめるか」を担当する。

## 2. 共通 API

基本形は次のとおり。

```bash
bk_profiler <tool> [options] -- <command ...>
```

現時点で共通 option として扱うものは次。

- `--level <single|simple|standard|detailed>`
- `--report-format <text|csv|both>`
- `--archive <path>`
- `--raw-dir <dir>`

環境変数でも次を上書きできる。

- `BK_PROFILER`
- `BK_PROFILER_TOOL`
- `BK_PROFILER_LEVEL`
- `BK_PROFILER_REPORT_FORMAT`
- `BK_PROFILER_ARGS`
- `BK_PROFILER_REPORT_ARGS`
- `BK_PROFILER_DIR`
- `BK_PROFILER_STAGE_DIR`
- `BK_PROFILER_ARCHIVE_NCU_REPORT`

`BK_PROFILER` / `BK_PROFILER_TOOL` は profiler tool の共通入口で、`none` / `off`
などを指定すると profiler を使わない。新規 app wrapper では、tool と level の解決に
`bk_resolve_profiler_tool` / `bk_resolve_profiler_level` を使う。既存運用や site-local
調整のために app 固有変数が必要な場合は、共通変数の上書きとして helper に渡す。

## 3. 共通語彙としての level

`single/simple/standard/detailed` は BenchKit の共通語彙として扱う。
ただし、その具体的意味は profiler tool ごとに adapter が定義する。

このため、ある tool では複数の測定 run に対応し、別の tool では単一 run の profiler option や採取範囲に対応してよい。

## 4. `fapp` の level 定義

`fapp` では現在、次の対応を採る。

- `single` → `pa1`
- `simple` → `pa1..pa5`
- `standard` → `pa1..pa11`
- `detailed` → `pa1..pa17`

既定の report format は次。

- `single` → `text`
- `simple` → `both`
- `standard` → `both`
- `detailed` → `both`

ここでいう CSV は `fapp` 固有の CPU performance analysis report を指す。
BenchKit は「CSV があること」を共通必須にはしない。

## 5. `ncu` の level 定義

`ncu` では現在、次の対応を採る。

- `single` → `--set basic --launch-count 1`
- `simple` → `--set basic --launch-count 5`
- `standard` → `--set full --launch-count 1`
- `detailed` → `--set full --nvtx`

既定の report format は `text` とする。
`padata*.tgz` の肥大化を避けるため、Nsight Compute の binary report (`*.ncu-rep` など) は既定では archive から除外する。
可能な場合は `ncu --import ... --page details` の出力を `bk_profiler_artifact/reports/ncu_import_rep1.txt` に保存する。
`BK_PROFILER_NCU_RAW_CSV=true` の場合は、推定 package が使う raw CSV を `bk_profiler_artifact/raw/rep1/profile_raw.csv` に保存する。
binary report も保存したいデバッグ用途では、`BK_PROFILER_ARCHIVE_NCU_REPORT=true` を明示する。

MPI launcher 経由の GPU application では、既定で `--target-processes all` を付けて child process も採取対象にする。
追加の kernel filter、section set、NVTX filter などは `BK_PROFILER_ARGS` で `ncu` に渡す。

### 5.1 GPU kernel discovery と NCU plan

GPU 性能推定では、アプリ側が kernel 名、launch skip/count、NCU metric list を事前調査して手書きする運用を最終形にしない。
BenchKit 共通層は、次の段階的 flow を目標にする。

1. profiler overhead のない通常実行で FOM と app section timing を取る。
2. 軽量な discovery 実行で `nsys stats --report cuda_gpu_kern_sum --format csv` 相当の kernel summary を得る。
3. summary から GPU 時間の上位 kernel を選び、`ncu_plan.json` を生成する。
4. `ncu_plan.json` に従って、選ばれた代表 kernel launch だけを Nsight Compute で深掘りする。
5. 推定 package は raw NCU CSV / prepared CSV を入力にし、section time への掛け算に使う source/target ratio を返す。

このためのオフライン変換 helper として、`scripts/profiling/generate_ncu_plan.py` を提供する。
この helper は `nsys` や `ncu` を実行せず、CSV fixture だけでテストできる。

```bash
python3 scripts/profiling/generate_ncu_plan.py \
  --nsys-csv results/nsys_cuda_gpu_kern_sum.csv \
  --out-discovery results/kernel_discovery.json \
  --out-plan results/ncu_plan.json \
  --top-k 0 \
  --launch-count 10
```

`kernel_discovery.json` は kernel 名、呼び出し回数、合計 GPU 時間、平均時間を正規化した summary である。
`ncu_plan.json` は共通 profiler 層や app wrapper が NCU 採取に使える候補 plan で、各 profile に次を含む。
`--top-k 0` は discovery 調査用に全 kernel を plan へ残す指定である。
NCU 実行時は、NSYS で同定した kernel に対して `launch_skip=1` / `launch_count=10`
程度の小さな window から始める。`discovery_gpu_time_pct` は NSYS で観測された
GPU kernel 時間内の割合であり、app FOM 全体に対する割合ではない。

- `kernel_name`
- `kernel_match.name_base`
- `kernel_match.pattern`
- `launch_skip`
- `launch_count`
- `metric_set`
- `selection.source_gpu_duration_ns`
- `selection.discovery_gpu_time_pct`
- `archive_ncu_report`
- `selection` metadata

現時点の helper は app section との対応を自動確定しない。
NVTX range や app-side section timing と接続できる場合は、将来 `section` を埋める拡張で section-aware discovery に進める。
NVTX がない場合でも、アプリ全体の上位 GPU kernel を自動抽出することで、手書きの kernel regex / skip / count を減らせる。

GPU 実機で走らせる前には、plan を `bk_profiler ncu` の dry-run command manifest に変換して確認できる。

```bash
python3 scripts/profiling/render_ncu_plan_commands.py \
  --plan results/ncu_plan.json \
  --out results/ncu_commands.json \
  --level detailed \
  -- ./app --input case.inp
```

この manifest は profile ごとの `BK_PROFILER_ARGS`、archive path、raw-dir、`bk_profiler ncu` argv を持つ。
現段階では実行は app wrapper や site runner 側が行い、共通 helper は「自動生成された NCU 採取内容を inspect 可能にする」ことを担当する。

## 6. Archive の考え方

`bk_profiler` は archive の中に少なくとも次を置く。

```text
bk_profiler_artifact/
  meta.json
  raw/
  reports/
```

`raw/` と `reports/` の具体的中身は profiler ごとに異なってよい。

例:

```text
bk_profiler_artifact/
  meta.json
  raw/
    rep1/
    rep2/
  reports/
    fapp_A_rep1.txt
    cpu_pa_rep1.csv
    fapp_A_rep2.txt
    cpu_pa_rep2.csv
```

## 7. `meta.json` の役割

`meta.json` は、archive の内容を BenchKit や推定 package が機械的に判断するための最小 metadata とする。

例:

```json
{
  "tool": "fapp",
  "level": "detailed",
  "report_format": "both",
  "raw_dir": "raw",
  "runs": [
    {
      "name": "rep1",
      "event": "pa1",
      "raw_path": "raw/rep1",
      "reports": [
        {"kind": "summary_text", "path": "reports/fapp_A_rep1.txt"},
        {"kind": "cpu_pa_csv", "path": "reports/cpu_pa_rep1.csv"}
      ]
    }
  ]
}
```

これにより、将来は BenchKit や estimation package が

- `tool`
- `level`
- `reports[].kind`

を見て、その artifact が適用可能かどうかを判断できる。

## 8. アプリ側の責務

アプリ側は profiler helper を直接一般化しすぎず、次だけを持てばよい。

- どの system で profiler を使うか
- 既定でどの tool / level を使うか
- app 固有または site-local の profiler 上書き変数を許すか
- build 時に profiler 用 option が必要か

例として、ある app wrapper では、

- Fugaku 系 build で必要なら `profiler=fapp` を渡す
- run で `bk_resolve_profiler_tool fapp APP_PROFILER_TOOL` と
  `bk_resolve_profiler_level detailed APP_PROFILER_LEVEL` を使う
- 解決された tool が空でなければ `bk_profiler "$tool" --level "$level" -- ...` を呼ぶ

だけを持つ。

GPU アプリごとの kernel window、module、compiler wrapper、短縮 input、profile 回数、archive の分割方針はアプリ wrapper の責務です。
BenchKit 共通層と推定 package 層は、これらのアプリ固有値を直接解釈しません。
共通層が扱うのは、app wrapper が生成した `padata*.tgz`、`SECTION:` metadata、`meta.json` などの共通 artifact だけです。

アプリ固有の環境変数は `programs/<code>/build.sh`、`programs/<code>/run.sh`、`programs/<code>/estimate.sh` の内部で、同じアプリ内の重複を減らすために使います。
共通 CI/matrix、共通 profiler helper、推定 package は、そのアプリ固有変数が存在することを前提にしないでください。
特定 app の profiling 例や kernel-to-section mapping は `programs/<code>/` 側に置きます。

## 9. 今は固定しないこと

現時点では、次は固定しない。

- profiler 間で report filename を完全統一すること
- CSV を全 profiler 共通の必須形式にすること
- level の語彙をすべての profiler に強制すること
- `meta.json` の詳細 schema を過度に厳密化すること

まずは

- raw/report を archive にまとめる
- `meta.json` で判別可能にする
- app 側から再利用しやすい API を保つ

ことを優先する。
