# QWS BenchKit Integration Notes

This directory owns QWS-specific build, run, and estimation settings. Shared
BenchKit CI, top-level estimation packages, and section packages should not
depend on QWS-local variables or dummy section names.

## Estimation Sections

`programs/qws/estimate.sh` is a reference lightweight app wrapper. It declares
the section names and the section-package mapping locally, then passes measured
or synthetic section timings to the common BenchKit estimation layer.

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

The current QWS section timings are synthetic fractions of the benchmark FOM.
They are useful for exercising the common estimation framework and portal
display, but they are not a substitute for app-side timers from QWS itself.

## Responsibility Split

QWS-owned code should decide:

- which application sections exist
- how section timings are obtained from QWS output or test fixtures
- which section package each section should use

Common BenchKit code should handle:

- package loading and fallback
- section and overlap composition
- current/future system Estimate JSON construction
- result-server artifact upload and portal rendering
