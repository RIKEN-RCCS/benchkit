
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
