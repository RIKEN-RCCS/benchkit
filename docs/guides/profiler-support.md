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

## 3. 共通語彙としての level

`single/simple/standard/detailed` は BenchKit の共通語彙として扱う。
ただし、その具体的意味は profiler tool ごとに adapter が定義する。

このため、ある tool では 4 段階すべてを持ってもよいし、別の tool では 1 段階だけでもよい。

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
raw report は `raw/rep1/profile*.ncu-rep` または Nsight Compute の出力形式に従う report file として保存し、可能な場合は `ncu --import ... --page details` の出力を `reports/ncu_import_rep1.txt` に保存する。

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
- Fugaku 系 run で `bk_profiler fapp --level single -- ...` を呼ぶ

だけを持つ。

`genesis` では、MiyabiG と RC_GH200 を同じ Grace-Hopper GPU 系の計算ノードとして扱い、GPU build / run に対して、

- build で `--enable-gpu`、`--enable-openmp`、`--with-gpuarch=sm_90` を指定する
- MiyabiG の既定 build では外部 LAPACK を要求せず、必要な場合だけ `GENESIS_MIYABIG_LAPACK_LIBS` で有効化する
- `.fpp` 前処理では GENESIS の traditional cpp flags を保持しつつ、GPU/single/MPI/OpenMP/FFTE の define を `PPFLAGS` 経由で明示する
- CUDA 12.9 以降向けに `src/spdyn/gpu_sp_energy.cu` の `nvToolsExt.h` include を `nvtx3/nvToolsExt.h` に補正する
- `mpif90` の実体が `nvfortran` の環境向けに、GENESIS の compiler 判定を NVHPC/PGI 系として補正する
- GENESIS の古い PGI flag (`-Mcuda` など) は `configure.ac` 側で NVHPC 25.x/aarch64 向けの `-cuda -gpu=cc90` へ補正する
- NVHPC 25.x では古い PGI pinned-array 経路の `PGICUDA` define を外し、GPU kernel 用の domain fields を保持する
- run では、`ncu` が PATH にある場合に `bk_profiler ncu --level single -- ...` を呼ぶ

形を参照実装とする。ジョブ投入方式は MiyabiG が PBS、RC_GH200 が SLURM で異なるが、アプリ側の実行方法と profiler 採取方法は共通化する。

CUDA prefix、compiler wrapper、module、profiler tool は site 側の module 構成に合わせて上書きできる。

- build/run 共通の module: `GENESIS_MIYABIG_MODULE`, `GENESIS_GH200_MODULE`
- build 時の CUDA/compiler/config: `GENESIS_MIYABIG_CUDA_PATH`, `GENESIS_MIYABIG_FC`, `GENESIS_MIYABIG_CC`, `GENESIS_MIYABIG_CONFIG_ARGS`
- run 時の profiler: `GENESIS_MIYABIG_PROFILER_TOOL`, `GENESIS_GH200_PROFILER_TOOL`, `GENESIS_MIYABIG_PROFILER_LEVEL`, `GENESIS_GH200_PROFILER_LEVEL`, または共通の `GENESIS_PROFILER_TOOL` / `GENESIS_PROFILER_LEVEL`

Genesis GH200 run の profiler 既定値は `ncu` だが、これは暗黙の既定値としてだけ扱う。`ncu` が PATH にない環境では warning を出して profiler なしで benchmark 本体を実行する。
一方、`GENESIS_PROFILER_TOOL=ncu` または system 固有の `GENESIS_*_PROFILER_TOOL=ncu` を明示した場合は、`ncu` が見つからなければ失敗させる。
profiler なしを明示したい場合は、`GENESIS_PROFILER_TOOL=none` または system 固有の `GENESIS_*_PROFILER_TOOL=none` を指定する。

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
