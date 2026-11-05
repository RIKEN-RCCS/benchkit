## RIKYU CPU route

This route runs the existing Generic, Oct and Oct_mod1 kernels on Grace CPUs,
using GNU Fortran, OpenMP and `MARCH=armv9-a+sve2`. Required tools are gfortran
(with support for that target), cpp, make and bzip2. Build and run hosts must
provide compatible libgfortran and libgomp runtimes.

The matrix requests one node, one process and 32 CPU threads for ten minutes.
The RIKYU queue template also reserves one GPU; the kernels do not use it.
The thread count respects the site's 32-CPU-per-GPU allocation limit. `srun`
requests the same CPU count, with core binding; OpenMP uses core places and
close binding. This is a CPU benchmark, not a GPU throughput measurement.

Inputs come from the recorded upstream source commit. Existing expanded inputs
are read in place; otherwise the two bundled bzip2 files are expanded once in
the run checkout, preserving the compressed originals. Expanded inputs total
approximately 6 GB and stay in the run checkout. Each kernel must pass its three
upstream numerical checks and report a positive time FOM.

## Flow2 Type II CPU route

The Type II route builds on the aarch64 compute node with GNU Fortran and
`MARCH=armv8.2-a+sve`; it does not reuse Type I's x86 compiler target.
Required tools are gfortran, cpp, make and bzip2. Inputs are included in the
upstream repository. Generic, Oct and Oct_mod1 retain their original numerical
checks and per-kernel time FOM. Each case must report all three upstream checks
as successful; a failed case does not emit a FOM.

The enabled matrix entry uses one node, one process and 72 OpenMP threads
with a 30-minute limit including native compilation. Normal CI uses the
Flow2 Type II queue template (t2-single). Scheduler validation was completed
on t2-debug with all three numerical checks passing for each case. This is
a Grace CPU route and does not use GPU kernels.
