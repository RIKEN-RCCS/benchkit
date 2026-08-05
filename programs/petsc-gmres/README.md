# petsc-gmres

A PETSc KSP (GMRES + GAMG algebraic multigrid preconditioner) benchmark:
load the `audikw_1` sparse SPD matrix ([SuiteSparse Matrix
Collection](https://sparse.tamu.edu/GHS_psdef/audikw_1), `GHS_psdef`
group — a real structural-engineering FEM problem, 943,695 rows,
77,651,847 nonzeros), solve `Ax = b` for a known `x`, report the relative
L2 error and solve wall-time (`FOM: ranks=<N> solve_time_s=<t>`).

Source (`src/GMRES-PETSc.cpp`) is vendored directly in this directory
rather than fetched from a separate repo at build time, since its
upstream development happens in a private RIKEN-RCCS repository. PETSc
itself is fetched normally via `bk_fetch_source` from its official repo,
pinned to `v3.25.2`.

Confirmed working on Rikyu (GB200 NVL4), Fugaku (A64FX), and R-CCS
Cloud's DGX Spark (`RC_DGXSP`, GB10 Blackwell) — see this app's `build.sh`
for the per-system recipe. Full strong-scaling results, root-cause
diagnoses for a couple of real bugs found getting each port working
(a matrix-distribution bug causing OOM, a GAMG coarsening crash on this
matrix's connectivity, an MPI-transport gotcha on one system), and the
underlying build recipes are documented in more depth in that same
internal repository — not linked here since it isn't publicly readable,
but available to RIKEN-RCCS members on request.

## Correctness

`relative L2 norm of the error` should land near 0.03–0.04 at any rank
count (GMRES's default relative-residual tolerance, not a tight solve —
this is a benchmark, not a production accuracy target). A result outside
that band signals a real bug, not benchmark noise.

## `-pc_gamg_square_graph 0`

Required on every system, at any rank count above 1 (single-rank runs
happen not to trigger it, but don't rely on that). Without it, GAMG's
default aggressive-coarsening graph-squaring step blows up on
`audikw_1`'s connectivity — a `CUSPARSE_STATUS_INSUFFICIENT_RESOURCES`
crash on GPU, or a genuine multi-GB single-allocation PETSc "Out of
memory" abort on CPU. Both `build.sh`'s configure line and `run.sh`'s
launch command already account for everything needed except this flag,
which is passed explicitly in `run.sh`.

## Staging the data

The matrix is pre-converted once (offline, not part of `build.sh`/`run.sh`)
from MatrixMarket format to PETSc's binary format via a small one-time
conversion tool (also part of the private upstream repo, not shipped
here — it's not needed at benchmark build/run time, only to produce the
staged file below once). This avoids every rank re-parsing a
multi-hundred-MB text file at load time, which was the actual root cause
of the original reported "runs out of memory for no reason" bug this
benchmark exists to catch a regression of.

Pre-staged locations (same convention as this repo's `ffb` and
`LQCD_dw_solver`, which pre-stage their own — much larger — source
archives at a fixed per-system path rather than fetching them at
build/run time):

| system | path |
|---|---|
| RIKYU | `/data1/rkp00015/benchkit-data/petsc-gmres/audikw_1.petscbin` |
| Fugaku | *(not yet staged — group-storage quota exhausted on the volumes covered by this repo's `FJ` queue.csv `GFSCACHE` declaration; `Fugaku` row is `enable=no` in `list.csv` until this is resolved)* |
| RC_DGXSP | *(not yet staged; `RC_DGXSP` row is `enable=no` in `list.csv` until this is resolved)* |

To re-stage on a system with an existing PETSc install: download
`audikw_1.mtx` from the SuiteSparse Matrix Collection link above, then use
PETSc's own `MatLoad`/`MatView` binary-viewer round trip (or the private
repo's `mtx2petsc` tool, if you have access) to write it to PETSc binary
format. Verify the result: 943,695 × 943,695, nnz = 77,651,847 — the
standard SuiteSparse download is MatrixMarket `symmetric` format (one
triangle + diagonal only), so a correct converter must mirror off-diagonal
entries; a naive read of the file as-is will silently produce a wrong,
singular matrix with no error.
