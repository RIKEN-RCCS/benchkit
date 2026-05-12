# Profiler Level Reference

This note complements `bk_profiler` and focuses on the shared level names used by BenchKit.

## Shared Levels

- `single`
  - minimal profile coverage
- `simple`
  - lightweight profile coverage
- `standard`
  - standard profile coverage
- `detailed`
  - detailed profile coverage

These names are BenchKit-level presets. Each profiler adapter defines the concrete behavior behind them.
For example, `fapp` maps these levels to multiple event-set runs, while `ncu` maps them to Nsight Compute options such as section set, launch count, and NVTX filtering.

## Current `fapp` Mapping

- `single`
  - event set `pa1`
- `simple`
  - event set `pa1..pa5`
- `standard`
  - event set `pa1..pa11`
- `detailed`
  - event set `pa1..pa17`

Default report behavior for `fapp` is:

- `single`
  - `text`
- `simple`
  - `both`
- `standard`
  - `both`
- `detailed`
  - `both`

Here `both` means text summaries plus CSV reports.

## Current `ncu` Mapping

- `single`
  - `--set basic --launch-count 1`
- `simple`
  - `--set basic --launch-count 5`
- `standard`
  - `--set full --launch-count 1`
- `detailed`
  - `--set full --nvtx`

Default report behavior for `ncu` is `text`.
BenchKit stores the Nsight Compute raw report under `bk_profiler_artifact/raw/rep1/` and, when import succeeds, a text details page under `bk_profiler_artifact/reports/ncu_import_rep1.txt`.

## Portal Summary

BenchKit stores profiler metadata in `bk_profiler_artifact/meta.json` inside `padata.tgz`, and also copies a compact summary into `result.json` as `profile_data`.

This makes it possible to inspect profiler coverage without downloading the archive first.

- Results list
  - `Profiler` shows `tool / level`
  - the secondary line shows `report_format` and run count
- Result detail
  - `PA Data Summary` shows tool-specific details, explicit events when applicable, NCU options when present, and report kinds

## Why This Helps

The summary is compact enough for portal browsing, while `meta.json` remains rich enough for future estimation packages to judge applicability from:

- `tool`
- `level`
- `report_kinds`
