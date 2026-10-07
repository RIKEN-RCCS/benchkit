# Security Policy

Benchkit is published as open source, so security fixes and reporting paths
need to be clear for external users and researchers.

## Supported Versions

| Version or branch | Supported |
| --- | --- |
| `main` | Yes |
| `develop` | Yes, for upcoming fixes before release |
| Older untagged revisions | No |

## Reporting a Vulnerability

Please report suspected vulnerabilities privately instead of opening a public
issue.

- GitHub private vulnerability reports: https://github.com/RIKEN-RCCS/benchkit/security/advisories/new

Include the affected component, impact, reproduction steps, proof of concept
details if available, and any suggested fix. Do not include real secrets,
credentials, or personal data in the report.

## Response Targets

These targets apply to Benchkit issues in scope below, not to upstream release
schedules or patch deployment on independently operated servers.

| Step | Target |
| --- | --- |
| Initial acknowledgement | Within 3 business days |
| Triage | Within 7 business days |
| Critical or High severity patch | Within 30 days |
| Medium severity patch | Within 90 days |
| Coordinated disclosure | After a fix is available, usually within 30 to 90 days |

## Scope

In scope:

- `result_server` authentication, authorization, ingestion, and portal routes
- CI and runner integration that could expose credentials or corrupt results
- Deployment guidance that could lead to insecure production defaults

Out of scope:

- Social engineering
- Attacks requiring already-compromised infrastructure outside this repository
- Defects confined to third-party software, whose fixes are maintained upstream;
  affected Benchkit dependency constraints, integration, and defaults remain in scope
- Local development configurations intentionally bound to loopback interfaces

## Dependency and Deployment Responsibilities

Benchkit documents the external dependencies, supported or minimum versions,
and configuration needed to build and run a CX server. Requirements and test
pins describe compatibility or a tested installation, not a security guarantee
or the installed software on any particular server.

Benchkit maintainers are responsible for vulnerabilities in Benchkit code,
unsafe integration or defaults, and dependency constraints or installation
guidance that prevent a supported secure deployment. Maintainers monitor
security advisories for dependencies selected or specified by Benchkit, assess
their impact on supported Benchkit versions, and provide requirement updates,
compatibility fixes, or mitigation guidance as needed. Operators apply and
validate the applicable changes in their own deployments.

Each CX server operator is responsible for its deployed software, including
the OS, reverse proxy (such as nginx), Bash, jq, curl, Python, database libraries
(such as SQLCipher), and their dependencies. Operators must monitor applicable
security advisories, assess exposure, and apply and validate updates or
mitigations. A compatibility minimum or a repository pin does not replace this
work; neither the Benchkit project nor the CX framework operates or patches an
independently deployed server.

Public dependency documentation is for installation and compatibility. Operators
are not required to publish installed-version inventories, infrastructure
configuration, or operational vulnerability records in this repository. Keep
those records under the operator's access controls. This does not restrict
coordinated publication of Benchkit security advisories describing affected
versions and remedies without deployment-specific information. Build provenance and
redistribution reviews are driven by the actual distribution model, a specific
risk, or the operator's policy, not a blanket requirement for using a library.
Applicable license obligations still apply when distributing third-party code
or binaries, including prebuilt images.

## Security Updates and Downstream Users

Security updates and guidance are communicated through the project's
[published security advisories](https://github.com/RIKEN-RCCS/benchkit/security/advisories)
and release notes, as appropriate. Deployment operators and fork maintainers
are responsible for monitoring these channels and applying relevant changes.
The project does not undertake to identify every downstream fork or deployment,
contact each individually, or verify receipt or installation of updates.
This policy does not override any separate contractual or applicable legal
obligations.

We appreciate coordinated disclosure and will credit reporters when requested.
