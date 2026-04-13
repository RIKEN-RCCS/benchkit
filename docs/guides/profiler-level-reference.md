# Profiler Level Reference

This note complements `bk_profiler` and focuses on the shared level names used by BenchKit.

## Shared Levels

- `single`
  - one measurement run
- `simple`
  - five measurement runs
- `standard`
  - eleven measurement runs
- `detailed`
  - seventeen measurement runs

These names are BenchKit-level presets. Each profiler adapter defines the concrete behavior behind them.

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

## Portal Summary

BenchKit stores profiler metadata in `meta.json` inside `padata.tgz`, and also copies a compact summary into `result.json` as `profile_data`.

This makes it possible to inspect profiler coverage without downloading the archive first.

- Results list
  - `Profiler` shows `tool / level`
  - the secondary line shows `report_format` and run count
- Result detail
  - `PA Data Summary` shows tool-specific events, explicit events, and report kinds

## Why This Helps

The summary is compact enough for portal browsing, while `meta.json` remains rich enough for future estimation packages to judge applicability from:

- `tool`
- `level`
- `report_kinds`
