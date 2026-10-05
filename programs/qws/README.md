# QWS Benchkit Integration Notes

This directory owns QWS-specific build, run, and estimation settings. Shared
Benchkit CI, top-level estimation packages, and section packages should not
depend on QWS-local variables or dummy section names.

## Flow2

Both Flow2 routes initially run CPU-only CASE0 on one node with one MPI rank.
Thread counts and time limits are application settings in `list.csv`, not
full-node scheduler reservation sizes. Other MPI layouts are rejected because
CASE0 has a single-rank process grid.

| System | Modules | Build location |
| --- | --- | --- |
| `Flow2_Type1` | `oneapi/2026.1.0`, `impi/2021.18` | Login node, separate from the PBS run job |
| `Flow2_Type2` | `nvhpc/26.5`, `nv-hpcx/26.5` | ARM64 compute node, inside the PBS run job |

Type I uses Intel MPI wrappers with an explicit `-march=x86-64-v4` target for
AMD CPUs instead of QWS's Intel-only `-xCORE-AVX512` default. See the
[Intel compiler target documentation](https://www.intel.com/content/www/us/en/docs/dpcpp-cpp-compiler/developer-guide-reference/2024-0/march.html).
Type II uses QWS's Grace CPU implementation, with `mpic++ -mp` for C++/OpenMP;
it does not offload to the GPUs reserved by the single-node queue. Its time
limit includes compilation. Both routes retain QWS's output validation and
solver-time FOM extraction.

Module loading has been checked on both node types. The single-node queues
accept `select` with MPI/OpenMP layout and determine CPU/GPU reservations
without explicit `ncpus` or `ngpus`. Held-job acceptance has been checked, but
QWS compilation and execution still require validation on the actual nodes.

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
