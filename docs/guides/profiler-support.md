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

- `BK_PROFILER_LEVEL`
- `BK_PROFILER_REPORT_FORMAT`
- `BK_PROFILER_ARGS`
- `BK_PROFILER_REPORT_ARGS`
- `BK_PROFILER_DIR`
- `BK_PROFILER_STAGE_DIR`
- `BK_PROFILER_ARCHIVE_NCU_REPORT`

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
- どの tool を使うか
- どの level を使うか
- build 時に profiler 用 option が必要か

例として `qws` では、

- Fugaku 系 build で `profiler=fapp` を渡す
- Fugaku 系 run で `bk_profiler fapp --level detailed -- ...` を呼ぶ

だけを持つ。

GPU アプリごとの kernel window、module、compiler wrapper、短縮 input、profile 回数、archive の分割方針はアプリ wrapper の責務です。
BenchKit 共通層と推定 package 層は、これらのアプリ固有値を直接解釈しません。
共通層が扱うのは、app wrapper が生成した `padata*.tgz`、`SECTION:` metadata、`meta.json` などの共通 artifact だけです。

アプリ固有の環境変数は `programs/<code>/build.sh`、`programs/<code>/run.sh`、`programs/<code>/estimate.sh` の内部で、同じアプリ内の重複を減らすために使います。
共通 CI/matrix、共通 profiler helper、推定 package は、そのアプリ固有変数が存在することを前提にしないでください。
GENESIS の現在の GH200 GPU profiling 例は `programs/genesis/README.md` と `programs/genesis/run.sh` に置いています。

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
