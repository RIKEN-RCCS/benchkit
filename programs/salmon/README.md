# SALMON benchmark

`build.sh` selects the site's existing SALMON source ref and compiler settings.
`SALMON_SOURCE_COMMIT` can require a full commit SHA without changing that ref.
Build artifacts contain the executable; the benchmark input is supplied
separately by the application.

For pre-staged TDDFT cases, `run.sh` reads the existing restart through a symlink.
Only the small namelist and pseudopotentials are copied into the run directory.
Parallel layout changes affect that namelist copy; the physical system and
number of time steps come from the original input. Input provenance records identify the supplied input.

RIKYU's four-process-per-node case runs both orbital and mixed decompositions.
The FOM remains SALMON's `rt iterations` time in seconds for each layout;
restart-read wall time is excluded. Missing, nonnumeric or nonpositive iteration
times fail the run. Completion markers and a valid timer are execution checks,
not a numerical accuracy test or a performance threshold.
