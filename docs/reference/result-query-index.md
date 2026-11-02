# Result Search and Usage Index

The optional candidate catalog also supplies Result search and Usage report
facts. JSON remains authoritative. The index is private, rebuildable derived
data, not another authoritative database or encrypted storage.

## Read Paths and Semantics

- Candidate-only pages do not scan Results. Search applies the existing exact
  filters, current visibility, counts and pagination in SQLite. Only the selected
  page is loaded from JSON, rechecking permissions and filters. Archive links use
  indexed filenames instead of directory listings. Details/comparisons/downloads
  retain their existing access checks.
  This does not index every detail/comparison/history API, the Estimate list or
  Version Check; those are separate consumers, not silently changed here.
- Node-Hours, Profile Operations, Performance Telemetry, Evidence Snapshot and
  its CSV share a read-only catalog snapshot within each report. SQL narrows
  periods/targets; existing calculation helpers consume small report records
  without opening source JSON. Configuration Checks still read definitions.
- Node-hour rounding, native/cross accounting, filename-derived dates and fiscal
  boundaries are unchanged. Available fiscal years retain their historical
  period-only scope, independent of System/Application matches. Profile
  attribution uses current definitions, retaining ambiguity and legacy fallback.

The catalog stores selected timing, resource, trigger/backend, snapshot summary,
cache and estimate fields. Evidence quality/public eligibility is derived with
the existing helpers. It does not copy complete JSON, arbitrary snapshot
payloads, logs, model data, source URLs or input manifests. Fact interpretation
changes require a version/rebuild decision, not silently mixing old/new facts.

The Profile DB metadata index retains its compatibility role and is not used for
public search or merged with this catalog. No Profile/Budget/Runner migration is
required. No scientific input gate, new FOM definition or automatic CI is added.

## Explicit Preparation

This procedure is for a separately approved deployment. Installing source code
does not perform it. The catalog remains disabled by default.

1. Identify all Result, Estimate and measurement archive roots and the catalog
   path used by every participating receiver/Web process. Bind empty Estimate
   and archive directories too. Shared Result/Estimate roots are supported.
2. Quiesce participating writers. Keep source files unchanged and preserve the
   old code/settings reference. A retained v1 derived catalog is an optional
   rollback artifact, not a backup of authoritative data.
3. Use an application-owned directory with mode 700, outside served roots;
   database/lock/sidecar files require mode 600.
4. Create and rebuild a NEW index explicitly:

   ```sh
   python -B scripts/result_catalog.py --catalog /private/index/results.sqlite3 \
     --results /private/results --estimates /private/estimates \
     --artifacts /private/measurement --initialize
   ```

   For a v1 candidate catalog use `--upgrade` instead of `--initialize`. Upgrade
   marks it unavailable before changing derived schema; a successful rebuild
   must follow. For v2 omit both flags. Supply all current roots on each rebuild,
   which explicitly replaces the root bindings. No source data is rewritten.
5. Compare scoped counts, a Result page and Usage/CSV with a known fixture or
   separately authorized copy. Apply the existing catalog setting consistently
   to participating processes only under deployment approval. No mixed writers.

## Failure and Rollback

Result, Estimate and archive publication share the writer lock and durable dirty
flag. Bytes are synchronized before index publication. Deletion hooks are
internal APIs, not new HTTP endpoints. Rebuild uses the same lock. Readers never
initialize/upgrade/rebuild an index.

After interruption, the source file may already exist although the receiver
returned 503. Do not blindly retry or resubmit: resolve receipt state and rebuild
under a separate operational decision. Incremental updates cannot clear an
incomplete baseline. Busy writers are not automatically retried.

Missing/dirty/incompatible/misbound enabled indexes never silently fall back to
full scans or report invented zero counts. Candidate pages show unavailability;
search/reports return a generic 503. Disabled installations retain the JSON path.
Direct edits/imports/removals and old receivers are not watched: quiesce writers,
keep the catalog unavailable and rebuild explicitly. Page-level permission
rechecks cannot prove the integrity of unvisited files.

For rollback, stop new writers first and restore the prior code/settings
reference. Old code cannot read v2. Disable the catalog for the original JSON
path, or rebuild an appropriate derived catalog with old code. Do not restore
source JSON or operational databases as an index rollback. Resume only one
compatible writer set after verification.

## Local Verification

```sh
python -B -m pytest -q result_server/tests/test_result_catalog.py \
  result_server/tests/test_result_catalog_routes.py \
  result_server/tests/test_result_query_index.py \
  result_server/tests/test_explicit_result_queries.py \
  result_server/tests/test_profile_usage_overview.py \
  result_server/tests/test_performance_telemetry.py \
  result_server/tests/test_evidence_snapshot.py
python -B scripts/tests/benchmark_result_queries.py --sizes 10000 100000
```

The benchmark generates disposable source files, a Profile fixture and index,
compares exact outputs for a 1/100 target and 50-row page, and reports time,
Python allocation peak, source JSON reads, directory scans and SQLite query
plans. Temporary inputs are removed. Optional `--output` creates a NEW summary
file, never replacing an existing file. No services/live data/CI are used.

Timings are local comparisons, not a latency SLA or cold-cache measurement.
Allocation/I/O instrumentation adds overhead, particularly to repeated JSON
parsing; compare read counts and query plans as well as elapsed seconds.
All-target reports still process selected rows. Memory depends on distinct
conditions/snapshot hashes and output size; deep numbered pages have offset
cost. Encrypted authoritative storage remains a separate future migration.

### Synthetic Measurement, 2026-11-02

Python 3.12.12 / SQLite 3.34.1, generated public Results, 100 Systems, one
Application, 1/100 selected, 50-row page. Estimate/archive directories are empty;
their correctness with nonempty data is covered by parity and receipt tests.
The JSON baseline runs before the indexed case, without dropping OS caches.
Times include allocation/I/O instrumentation and are not browser render times.

| Records | Operation | JSON seconds | Indexed seconds | Indexed source JSON reads |
| --- | --- | ---: | ---: | ---: |
| 10,000 | Result page | 4.285 | 0.064 | 100 |
| 10,000 | Node-Hours | 4.048 | 0.052 | 0 |
| 10,000 | Profile Operations | 3.566 | 0.031 | 0 |
| 10,000 | Performance Telemetry | 3.567 | 0.043 | 0 |
| 10,000 | Evidence Snapshot | 3.581 | 0.023 | 0 |
| 100,000 | Result page | 43.764 | 0.064 | 100 |
| 100,000 | Node-Hours | 40.770 | 0.501 | 0 |
| 100,000 | Profile Operations | 35.983 | 0.289 | 0 |
| 100,000 | Performance Telemetry | 36.198 | 0.449 | 0 |
| 100,000 | Evidence Snapshot | 35.972 | 0.217 | 0 |

All outputs matched. Indexed source directory scans were zero in every case.
The 50-row page uses the existing visibility loader, hence two JSON reads per
row. At 100,000 records, traced Python peak was about 188 KiB for the page and
30-42 KiB for reports, versus approximately 12.6-15.0 MiB on the JSON path.
These are Python allocation peaks, not process RSS or SQLite/OS cache memory.

Rebuild took 1.941 / 20.931 seconds; database sizes were 15,613,952 /
161,763,328 bytes. The report plan used `query_system` with directory, System
and timestamp range constraints. Allow about 1 GiB of disposable disk space and
several minutes for the largest instrumented fixture. These results do not
characterize all-target reports, high-cardinality snapshots, concurrent receipt,
network filesystems, production payload distribution or encrypted storage.
