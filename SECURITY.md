# Security Policy

BenchKit is published as open source, so security fixes and reporting paths
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
- Vulnerabilities in third-party dependencies that should be reported upstream
- Local development configurations intentionally bound to loopback interfaces

We appreciate coordinated disclosure and will credit reporters when requested.
