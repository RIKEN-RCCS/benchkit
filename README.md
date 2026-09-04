# Benchkit

Benchkit is a shell-first benchmarking framework for the CX Framework. It supports build and run workflows for multiple applications and systems, result collection, profiler data handling, estimation workflows, and result portal integration.

## Origin

Repository migration details are documented in [docs/repository-history.md](docs/repository-history.md).

## Purpose

- Run benchmarks across multiple codes and systems with a shared workflow.
- Support both cross-build and native execution environments.
- Keep site-specific configuration separate from benchmark logic.
- Collect result data, profiler outputs, and estimation inputs in a consistent format.
- Integrate with the CX result portal and related estimation workflows.
- Provide a practical base for performance analysis, estimation, and feedback.

## Quick Links

- Contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Add a new application: [docs/guides/add-app.md](docs/guides/add-app.md)
- Add a new system: [docs/guides/add-site.md](docs/guides/add-site.md)
- Add estimation support: [docs/guides/add-estimation.md](docs/guides/add-estimation.md)
- CI execution control: [docs/ci.md](docs/ci.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Profiler support guide: [docs/guides/profiler-support.md](docs/guides/profiler-support.md)
- Profiler level reference: [docs/guides/profiler-level-reference.md](docs/guides/profiler-level-reference.md)

## CX Framework Documents

Core specifications:

- [CX framework](docs/cx/CX_FRAMEWORK.md): top-level concept and terminology.
- [CX platform](docs/cx/CX_PLATFORM.md): system-level responsibilities and component boundaries.
- [Benchkit specification](docs/cx/BENCHKIT_SPEC.md): Benchkit responsibilities, interfaces, and future extension points.

Estimation and storage specifications:

- [Estimation](docs/cx/ESTIMATION_SPEC.md): common rules for accepting, running, storing, and presenting estimation functions.
- [Estimate JSON](docs/cx/ESTIMATE_JSON_SPEC.md): data-format requirements for stored estimation results.
- [Estimation input acquisition](docs/cx/ESTIMATION_INPUT_ACQUISITION_SPEC.md): handoff rules for inputs required by estimation packages.
- [Estimation package](docs/cx/ESTIMATION_PACKAGE_SPEC.md): responsibilities and structure of estimation packages.
- [Estimation package metadata](docs/cx/ESTIMATION_PACKAGE_METADATA_SPEC.md): metadata fields used to describe package identity, inputs, and fallback behavior.
- [Estimation package shell API](docs/cx/ESTIMATION_PACKAGE_SHELL_API_SPEC.md): shell-level interface for calling package implementations.
- [Re-estimation](docs/cx/REESTIMATION_SPEC.md): rules for re-running estimation from stored benchmark and estimation records.
- [Result storage design](docs/cx/RESULT_STORAGE_DESIGN.md): storage-design memo for result and estimate artifacts.

Operational specifications:

- [Audit log specification](docs/cx/AUDIT_LOG_SPEC.md): result-server audit log events and handling rules.

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

## Runtime Requirements

- `result_server` requires Python 3.12 or later.

## License

This project is licensed under the BSD 3-Clause License. See [LICENSE](LICENSE).
