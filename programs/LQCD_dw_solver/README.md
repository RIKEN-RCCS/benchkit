# LQCD domain-wall solver

The build obtains a new checkout from the source declared in `source.env`.
Existing `LQCD_dw_solver` directories are neither reused nor removed.
The existing `LQCD_DW_SOLVER_REPO_URL`, `LQCD_DW_SOLVER_BRANCH`, and
`LQCD_DW_SOLVER_SOURCE_COMMIT` overrides remain supported. A change to these
values changes the build cache identity.

The older-source CUDA `init_prempi` workaround remains conditional. Its status,
file hashes and diff are recorded separately from the upstream commit. Each
binary has its own build configuration and hash, including separate OpenACC
and CUDA entries on GPU systems. Numerical acceptance criteria, launch
parameters and FOM definitions are unchanged.

`artifacts/runtime` contains the binaries, the upstream `run/` inputs and
`conf_04040408.txt`, retaining the relative gauge path in the YAML. This input
layout was checked against upstream commit
`01c803d7c0984f5a4a621acfab407d18eb4d488d`; a source override requiring additional
runtime files needs a corresponding update to the declared payload.
The directory also contains the source record, build provenance and an inventory
of names, permissions and file hashes. Cache storage preserves the whole set.

Run restores a new working copy from this payload without fetching source.
It generates `main.yaml` with the existing per-system conditions and records
that actual input through `bk_run`. Logs and FOM extraction use the restored
working directory. Old build artifacts without the runtime payload must be
rebuilt; there is no fallback to an unrelated checkout or branch tip.

Full config contents and source diffs stay in build/CI artifacts. Result
`source_info.build` contains their hashes and status, binary associations and
the digest of the complete provenance record, not raw source or config text.
Integrity checks detect changed or missing handoff files; they are not a
signature, a scientific input approval, or proof of reproducible compilation.

Synthetic tests use local Git, fake compilers/launchers and generated logs.
They do not validate real MPI/CUDA compilation or numerical accuracy.
