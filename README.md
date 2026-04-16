# BenchKit

BenchKit is a shell-first benchmarking framework for the CX Framework. It supports build and run workflows for multiple applications and systems, result collection, profiler data handling, estimation workflows, and result portal integration.

## Purpose

- Run benchmarks across multiple codes and systems with a shared workflow.
- Support both cross-build and native execution environments.
- Keep site-specific configuration separate from benchmark logic.
- Collect result data, profiler outputs, and estimation inputs in a consistent format.
- Integrate with the CX result portal and related estimation workflows.
- Provide a practical base for performance analysis, estimation, and feedback.

## Quick Links

- Add a new application: [docs/guides/add-app.md](docs/guides/add-app.md)
- Add a new system: [docs/guides/add-site.md](docs/guides/add-site.md)
- Add estimation support: [docs/guides/add-estimation.md](docs/guides/add-estimation.md)
- Profiler support guide: [docs/guides/profiler-support.md](docs/guides/profiler-support.md)
- Profiler level reference: [docs/guides/profiler-level-reference.md](docs/guides/profiler-level-reference.md)

## CX Framework Documents

- [docs/cx/CX_FRAMEWORK.md](docs/cx/CX_FRAMEWORK.md)
- [docs/cx/CX_PLATFORM.md](docs/cx/CX_PLATFORM.md)
- [docs/cx/BENCHKIT_SPEC.md](docs/cx/BENCHKIT_SPEC.md)
- [docs/cx/ESTIMATION_SPEC.md](docs/cx/ESTIMATION_SPEC.md)

## Developer Reference

The detailed developer-oriented reference has moved to docs:

- [docs/guides/developer-reference.md](docs/guides/developer-reference.md)

This includes:

- project structure
- result portal architecture
- CI pipeline structure
- configuration files
- CI execution control
- system-specific execution environments
- runtime requirements
