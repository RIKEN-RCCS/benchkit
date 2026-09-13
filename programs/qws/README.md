# QWS Benchkit Integration Notes

This directory owns QWS-specific build, run, and estimation settings. Shared
Benchkit CI, top-level estimation packages, and section packages should not
depend on QWS-local variables or dummy section names.

## Estimation Sections

`programs/qws/estimate.sh` is a reference lightweight app wrapper. It declares
the section names and the section-package mapping locally. QWS production runs
do not emit section timing metadata until those timings are measured by QWS
itself.
`parse_timing.sh` records the current QWS timing table and optional
`QWS_TIMER_SCHEMA_*` markers as `results/qws_timing_<Exp>.json` artifacts when
they are present, then registers them through Benchkit's common
`timing_observations` manifest. These artifacts are measurement evidence only;
they are not converted into `SECTION:` / `OVERLAP:` records until the QWS-owned
timer IDs and overlap windows are reviewed as reusable section metadata.

Current reference sections are:

```text
prepare_rhs
compute_hopping
compute_solver
halo_exchange
allreduce
write_result
```

The reference overlap is:

```text
compute_hopping,halo_exchange
```

Previous test scaffolding emitted synthetic section timings and dummy artifacts
as fractions of the benchmark FOM. That path is disabled for production because
fake section data is easy to confuse with measured application data.
The `estimate.disabled` marker also prevents CI matrix generation from adding
QWS estimate jobs on estimate-target systems such as MiyabiG and RC_GH200.

## Responsibility Split

QWS-owned code should decide:

- which application sections exist
- how section timings are obtained from QWS output or test fixtures
- which section package each section should use

Common Benchkit code should handle:

- package loading and fallback
- section and overlap composition
- current/future system Estimate JSON construction
- result-server artifact upload and portal rendering

Benchkit-local QWS glue may normalize QWS output into app artifacts, but should
not decide that a nested or inclusive timer is an additive section without a
QWS-side mapping.
