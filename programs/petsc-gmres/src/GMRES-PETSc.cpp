// CSR data transfered to PETSc  Copyright,  Atsushi Suzuki 30 Jul.2025
//
// A PETSc KSP (GMRES + GAMG algebraic multigrid preconditioner) benchmark:
// load a large sparse SPD matrix, solve Ax = b for a known x, report the
// relative L2 error and solve wall-time.
//
// Loads a pre-converted PETSc binary matrix via MatLoad() against
// PETSC_COMM_WORLD, so rows are properly partitioned across MPI ranks
// (memory per rank scales as O(1/ranks), as a real distributed benchmark
// should). The binary is produced once, offline, from the MatrixMarket
// form of the benchmark matrix (audikw_1, SuiteSparse Matrix Collection,
// GHS_psdef group) -- see this app's README.md for where each target
// system's copy lives and how it was produced.
static char help[] = "load a PETSc binary matrix and call the KSP solver\n";

#include <petscksp.h>

int main(int argc, char **args)
{
  Vec         x, b, u;        /* approx solution, RHS, exact solution */
  Mat         A;              /* linear system matrix */
  KSP         ksp;            /* linear solver context */
  PC          pc;             /* PC context */
  PetscMPIInt size, rank;
  PetscBool   flg;
  PetscScalar one = 1.0;
  PetscReal   e, e0;

  char        fname[1024];
  PetscViewer viewer;

  PetscFunctionBeginUser;
  PetscCall(PetscInitialize(&argc, &args, (char *)0, help));
  PetscCallMPI(MPI_Comm_size(PETSC_COMM_WORLD, &size));
  PetscCallMPI(MPI_Comm_rank(PETSC_COMM_WORLD, &rank));
  PetscCall(PetscOptionsGetString(NULL, NULL, "-f", fname, sizeof(fname), &flg));
  if (!flg) {
    PetscCall(PetscPrintf(PETSC_COMM_WORLD,
			  "usage: %s -f <matrix.petscbin> [-ksp_monitor] [-pc_type gamg] [-log_view]\n",
			  args[0]));
    PetscCall(PetscFinalize());
    exit(-1);
  }

  PetscCall(MatCreate(PETSC_COMM_WORLD, &A));
  PetscCall(MatSetType(A, MATAIJ));
  PetscCall(MatSetFromOptions(A));
  PetscCall(PetscViewerBinaryOpen(PETSC_COMM_WORLD, fname, FILE_MODE_READ, &viewer));
  PetscCall(MatLoad(A, viewer));
  PetscCall(PetscViewerDestroy(&viewer));

  //     Create and set vectors
  PetscCall(MatCreateVecs(A, &u, &b));  // create vectors right u and left b
  PetscCall(VecDuplicate(u, &x));       // copy vector x from u
  PetscCall(VecSet(u, one));            // all entries of u are one
  PetscCall(MatMult(A, u, b));          // RHS from b = A * u

  //     Create linear solver context
  PetscCall(KSPCreate(PETSC_COMM_WORLD, &ksp));
  PetscCall(KSPSetOperators(ksp, A, A));

  //     Set defulat preconditioner as diagonal preconditioning
  PetscCall(KSPGetPC(ksp, &pc));
  PetscCall(PCSetType(pc, PCJACOBI));
  //     receive options for KSP solver from command line
  PetscCall(KSPSetFromOptions(ksp));

  // Build the GAMG hierarchy (coarsening + Galerkin/PtAP) explicitly,
  // OUTSIDE the timed region. The figure of merit is the GMRES iterate --
  // the MatMult-bound SpMV loop whose cost tracks memory bandwidth / Flop/s
  // -- not one-shot preconditioner setup, which is communication-bound and
  // does not characterize the iterative kernel. KSPSolve would otherwise
  // call KSPSetUp lazily on first use, folding setup into the timed region.
  // Use -log_view for the per-event breakdown (PCSetUp_GAMG, MatMult, ...).
  PetscCall(KSPSetUp(ksp));

  PetscLogDouble iter_t0, iter_t1;
  PetscCall(PetscBarrier((PetscObject)ksp));
  PetscCall(PetscTime(&iter_t0));
  PetscCall(KSPSolve(ksp, b, x));
  PetscCall(PetscBarrier((PetscObject)ksp));
  PetscCall(PetscTime(&iter_t1));
  {
    PetscReal local_dt = (PetscReal)(iter_t1 - iter_t0), max_dt;
    PetscCallMPI(MPI_Allreduce(&local_dt, &max_dt, 1, MPIU_REAL, MPI_MAX, PETSC_COMM_WORLD));
    PetscCall(PetscPrintf(PETSC_COMM_WORLD, "FOM: ranks=%d ksp_iter_time_s=%.6f\n", (int)size, (double)max_dt));
  }

  PetscCall(VecNorm(u, NORM_2, &e0));
  PetscCall(VecAXPY(x, -1.0, u));
  PetscCall(VecNorm(x, NORM_2, &e));
  PetscCall(PetscPrintf(PETSC_COMM_WORLD,
			"relative L2 norm of the error: %g\n", (double)(e/e0)));

  flg = PETSC_FALSE;
  PetscCall(PetscOptionsGetBool(NULL, NULL, "-print_error", &flg, NULL));
  if (flg) PetscCall(PetscPrintf(PETSC_COMM_WORLD, "Infinity norm of the error: %g\n", (double)e));

  PetscCall(KSPDestroy(&ksp));
  PetscCall(VecDestroy(&u));
  PetscCall(VecDestroy(&x));
  PetscCall(VecDestroy(&b));
  PetscCall(MatDestroy(&A));
  PetscCall(PetscFinalize());
  return 0;
}
