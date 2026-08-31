# Public Portal Access Control Design

This document defines the intended access-control boundary for publishing the
CX Portal. It is deployment design guidance, not a site-local configuration
file. Do not record real IP ranges, hostnames, tokens, certificate paths, or
private service paths here.

## Goals

The public portal should expose scientifically useful benchmark information
while keeping operational and governance surfaces out of the public web
interface.

Public data should be useful on its own or interpretable within the CX Portal:

- application, case, and experiment identifiers
- public system metadata
- node/process/thread/GPU shape
- figure of merit, unit, and public breakdown values
- public source provenance that resolves to public repositories
- profiler artifacts such as NCU or fapp data only when the collection
  parameters and disclosure decision make them reproducible and meaningful

Public views should not expose information that mainly helps operate or attack
the service:

- pipeline IDs, job IDs, runner names, runner paths, and internal project names
- private mirror URLs, internal URLs, database paths, environment paths, or
  service names
- allocation project IDs, account/budget values, reviewer/approver data, and
  profile attribution internals
- login, admin, profile-request, confidential-result, estimated-result, and
  operations links
- raw artifacts or JSON records that have not passed a public-safe projection
  or explicit disclosure review

Route names are not secrets because the source repository is public. The
security boundary must not depend on obscurity. The deployed service should
still make restricted routes unreachable from the public internet.

## Access Classes

Use separate access classes instead of a single "admin IP" bucket.

| Class | Purpose | Primary gate |
| --- | --- | --- |
| Public browser | Anonymous public portal visitors | Route allowlist and public-safe rendering |
| Restricted viewer | Users allowed to see confidential or estimated results | Restricted network range, TOTP login, affiliation/role checks |
| Authenticated console user | Users allowed to create or inspect their own console-side requests | Restricted or collaboration network range, TOTP login, per-route checks |
| Operator | Portal operators and administrators | Narrow operator network range, TOTP login, admin role checks |
| Runner/API client | CI runners and trusted ingest/query clients | mTLS or runner-scoped API authentication, rate limits |

Restricted viewer and operator networks may differ. For example, confidential
or estimated results may need to be reachable from a wider collaboration or VPN
range than admin pages, but they still require login and per-user authorization.

## Route Allowlist

The initial public allowlist should be deliberately small.

| Route | Public | Restricted viewer | Authenticated console | Operator | Runner/API | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /` | yes | yes | yes | yes | no | Public home page. |
| `GET /changes` | yes | yes | yes | yes | no | Public broad-grained portal release notes. |
| `GET /systems` | yes | yes | yes | yes | no | Public system catalog. |
| `GET /results/` | yes | yes | yes | yes | no | Public results list, rendered with public-safe columns only. |
| `GET /results/detail/<filename>` | conditional | yes | yes | yes | no | Public only for public results and public-safe detail fields. |
| `GET /results/compare` | conditional | yes | yes | yes | no | Public only when every selected result is public and the rendered fields are public-safe. |
| `GET /static/*` | yes | yes | yes | yes | no | Static assets only. Keep secrets and generated private files out of static paths. |
| `GET /results/<filename>` | conditional | conditional | conditional | yes | no | Public only for PA archive downloads that match public result metadata. Raw JSON remains restricted. |
| `GET /results/environment-snapshots/*` | no by default | conditional | conditional | yes | no | Environment snapshots can contain operational context; expose only after redaction/public projection review. |
| `GET /results/confidential` | no | yes | conditional | yes | no | Must be hidden from public navigation and blocked by reverse proxy for public clients. |
| `GET /estimated/*` | no | yes | conditional | yes | no | Requires restricted network, TOTP, and affiliation/role checks. |
| `GET/POST /execution-profile-requests/*` | no | no by default | yes | yes | no | Authenticated console surface. Applicant access may be enabled for non-admin users behind an operator or collaboration network. |
| `GET/POST /admin/*` | no | no | no | yes | no | Operator-only; Flask admin role checks still apply. |
| `GET/POST /auth/*` | no | yes | yes | yes | no | Login/setup/logout should not exist on the public surface. |
| `GET /results/usage` | no | no | no | yes | no | Operations/admin report. |
| `GET/POST /api/ingest/*` | no | no | no | no | yes | CI ingest only. Prefer nginx-verified mTLS. |
| `GET /api/query/*` | no | no | no | no | yes | CI/query clients only unless a separate public read API is intentionally designed. |
| `/dev/*`, `/dev2/*` | no | no by default | no by default | yes | no | Development portals should not be public. |

The public allowlist should prefer rendered pages over raw files. PA data
archives may be public when they match public result metadata because they are
reproducible current-system measurement artifacts. Confidential-result PA data,
raw JSON, environment snapshots, and confidential/estimated artifacts remain
outside the public browser surface.

## Reverse Proxy Responsibilities

The reverse proxy should provide reachability control before requests arrive at
Flask:

- terminate TLS
- keep Gunicorn bound to loopback or a Unix socket
- allow only public routes from the public internet
- return `404` for restricted routes when the client is outside the allowed
  restricted or operator network
- keep restricted viewer and operator network lists separate
- protect runner API routes with mTLS or an equivalent trusted-client gate
- set security headers for restricted responses, including `Cache-Control:
  no-store` and `X-Robots-Tag: noindex, noarchive`

Do not base reverse-proxy IP allowlists on client-supplied headers such as
`X-Forwarded-For`. If another load balancer or CDN is inserted before nginx,
review the trusted proxy chain and forwarded-header handling before deployment.

Conceptual nginx layout:

```nginx
# Public routes: allow all.
location = / { proxy_pass http://portal_backend; }
location = /changes { proxy_pass http://portal_backend; }
location = /systems { proxy_pass http://portal_backend; }
location = /results/ { proxy_pass http://portal_backend; }
location /static/ { proxy_pass http://portal_backend; }

# Public only after Flask renders a public-safe projection.
location /results/detail/ { proxy_pass http://portal_backend; }
location = /results/compare { proxy_pass http://portal_backend; }

# Restricted viewer routes: restricted network first, then Flask auth/role.
location /estimated/ { return 404; }              # replace with restricted gate
location = /results/confidential { return 404; }  # replace with restricted gate

# Operator routes: narrow operator network first, then Flask auth/admin role.
location /admin/ { return 404; }                  # replace with operator gate
location /execution-profile-requests/ { return 404; }
location /auth/ { return 404; }

# Runner API: do not expose as a browser-public route.
location /api/ { return 404; }                    # replace with mTLS gate
```

The example intentionally omits real IPs and certificate settings. Site-local
nginx configuration should implement the restricted and operator gates using
deployment-managed allowlists.

## Flask Responsibilities

Flask should not rely on the reverse proxy alone. It should keep separate
rendering and authorization paths:

- public views receive only public-safe data
- public portal mode blocks restricted viewer, authenticated-console, auth,
  and operator browser endpoints at the Flask layer with `404`
- operator views may include pipeline, runner, trigger, profile, and allocation
  context where the user's role permits it
- confidential and estimated result routes require an authenticated session
  and per-user affiliation/role filtering
- raw JSON and artifact downloads check the same permission model as their
  corresponding rendered views
- navigation is split into public and operator surfaces
- public templates do not show login/admin/estimated/confidential/profile
  request links
- restricted responses use no-store caching headers
- access attempts to restricted routes are auditable at nginx and Flask layers

In the current codebase, public and confidential result lists are separate
(`/results/` and `/results/confidential`). When
`RESULT_SERVER_PUBLIC_PORTAL_MODE=true` is enabled for the public portal
deployment, public results list/detail/compare pages use a reduced public
surface:
raw JSON links, CI/pipeline columns, trigger internals, quality/validator rows,
and environment snapshot rows are hidden. PA archive links are kept when the
archive belongs to public result metadata. Raw result JSON and environment
snapshot routes return `404` in this mode. The same public-safe projection is
used even if an old authenticated session cookie is present on the public host.

The public portal Flask guard allows runner/API endpoints to reach their own
API authentication layer so that mTLS or runner-scoped API authentication can
continue to protect CI upload/query clients. Browser routes for auth, estimated
results, confidential results, profile requests, usage reports, and admin pages
are blocked by the Flask guard in addition to the reverse proxy policy.

Before publication, review the rendered public detail fields and any future
public artifact policy against this document.

The route access allowlist is also represented in
`result_server/utils/portal_access.py`. Tests should fail when a new Flask
endpoint is added without a conscious public, restricted-viewer,
authenticated-console, operator, or runner/API classification.

Set `RESULT_SERVER_PUBLIC_PORTAL_MODE=true` to make the deployment expose the
public browser surface: restricted links are hidden, rendered result pages use
the public-safe projection, and the Flask public-route allowlist blocks
restricted browser endpoints. Nginx reachability controls and Flask
authentication/authorization checks remain required.

Prefer setting this flag in the systemd `EnvironmentFile` used by the public
main portal deployment, alongside other result-server deployment mode flags
such as `RESULT_SERVER_TRUSTED_PROXY_AUTH`. Keeping deployment mode variables
in the `EnvironmentFile` leaves the service unit generic. For example, the
environment file should contain:

```sh
RESULT_SERVER_PUBLIC_PORTAL_MODE=true
```

Development or internal-only portal services may leave the flag unset unless
they intentionally need to preview the public browser surface.

Set `RESULT_SERVER_VERSION` to the deployed public tag when the production
checkout is not expected to sit exactly on a Git tag. If it is unset, the portal
shows the exact tag for `HEAD` when available, otherwise the current Git
description or `development`.

## Testing Plan

Add lightweight tests as the design is implemented:

- public navigation does not contain `Login`, `Admin`, `Estimated`,
  `Confidential`, `Profile`, `Allocation`, `Runner`, or `Pipeline`
- public results list and detail omit pipeline IDs, runner information,
  allocation values, internal URLs, and profile attribution internals
- unauthenticated access to confidential and estimated pages does not render
  protected data
- restricted raw JSON routes and non-public artifacts apply the same permission
  checks as rendered pages
- route classification tests cover every registered Flask route so new routes
  must be consciously classified as public, restricted viewer, operator, or
  runner/API
