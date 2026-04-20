# Contributing to BenchKit

Thank you for contributing to BenchKit.

This project aims to support an open ecosystem around the CX Framework and CX Platform. Contributions from application developers, system operators, and related communities are welcome.

## Before You Contribute

Please make sure that:

- your contribution is your own work, or you otherwise have the legal right to submit it under this project's license
- you are authorized to contribute it on behalf of your organization if your work is owned or controlled by that organization
- you understand that contributions to this repository are public and will be distributed under the repository license

## Developer Certificate of Origin

This project uses the Developer Certificate of Origin (DCO) instead of a separate contributor license agreement.

By submitting a contribution to this repository, you certify that:

- the contribution was created by you, in whole or in part, and you have the right to submit it under the open source license used by this project, or
- the contribution is based on previous work that may be submitted under a compatible open source license and you have the right to submit that work with your modifications

Please sign off each commit by using:

```bash
git commit -s
```

This adds a line like the following to your commit message:

```text
Signed-off-by: Your Name <your.email@example.com>
```

By submitting a contribution, you certify that you have the legal right to submit it under this project's license, either as an individual author or with the authorization of your organization.

Pull requests to protected branches must pass the DCO check.

For the full DCO text, see [https://developercertificate.org/](https://developercertificate.org/).

## Branch Model

- `develop`: default branch for ongoing development
- `main`: production branch used for merges from `develop`

## Pull Requests

When opening a pull request, please provide enough context for reviewers to understand:

- what problem is being addressed
- what changed
- whether any user-facing behavior changed
- whether tests or validation were run

For CI behavior and GitLab benchmark validation rules, see [CI Execution Control / CI実行制御](docs/ci.md).

## Scope

In general:

- framework, platform, and shared workflow improvements are welcome
- application and system support under `programs/` and related configuration are welcome
- documentation improvements are welcome

Project maintainers may ask for clarifications or follow-up changes before merge.
