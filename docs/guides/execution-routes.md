# Execution Route Presets

An execution route binds a GitLab project, runner tags, and an optional allocation for
one or more Benchkit systems. Different projects can execute the same system
under different user accounts and budgets without duplicating application
configuration. A route is an operational configuration, not a public activity
label or a mechanism for changing the operating-system user.

The project-file workflow below describes the current prototype. Budget-first
management is being developed around a shared [encrypted budget registry](budget-registry.md).
Its storage foundation, explicit Portal selection and snapshot handoff are
available. Budget-backed submission requires an explicitly enabled CI target/ref;
legacy profiles are not automatically migrated.

## Selected Snapshot Handoff

The Budget planner can supply `BK_EXECUTION_ROUTE_SNAPSHOT` as JSON containing
`version`, `registry_revision`, `budget_id`, `destination_id`, `target` and one
`route`. The route uses the fields below; its ID must equal `destination_id`, and
its systems list must contain exactly the system selected for matrix generation.
The generator validates the snapshot against the current GitLab server/project
and system catalog. An invalid or empty snapshot fails before job generation;
it never falls back to CSV tags. A snapshot cannot be combined with
`BK_EXECUTION_ROUTES_FILE`.

This handoff needs no manually maintained project-file copy. Bound Portal
profiles use it for manual, scheduled and watch submissions after the
[capability gate](budget-registry.md#enable-submission) is enabled. The CLI
validator accepts `--selected-system` with `--check` for snapshot validation.
Snapshot IDs and allocation are operational data, not public metadata. Do not
print the variable or treat it as proof of authorization; the access controls
described below still apply.

## Configure a Project

Create a GitLab project CI/CD variable named `BK_EXECUTION_ROUTES_FILE` with
**Type: File**, **Environment scope: `*`**, and variable expansion disabled.
GitLab supplies the temporary file path to the generator; see the
[file-variable documentation](https://docs.gitlab.com/ci/variables/#use-file-type-cicd-variables).
Its value is a JSON document such as this synthetic example:

```json
{
  "version": 1,
  "target": {
    "server_url": "https://gitlab.example.org",
    "project_path": "group/benchmarks"
  },
  "routes": [
    {
      "id": "research",
      "systems": ["Fugaku", "FugakuCN"],
      "build_tag": "research-build",
      "run_tag": "research-run",
      "allocation_project_id": "budget-example"
    }
  ]
}
```

Each project keeps its own complete configuration. The target must match
`CI_SERVER_URL` and `CI_PROJECT_PATH`; copying a configuration to another
project without updating its binding fails validation. A system may occur in
only one route. Cross-build systems require both tags; native systems require
only `run_tag`. IDs and tags use letters, digits, dots, underscores, colons, or
hyphens and must start with a letter or digit.

The generator requires Python 3 and jq. To validate a local file, set
`BK_EXECUTION_ROUTES_FILE`, `CI_SERVER_URL`, and `CI_PROJECT_PATH` in the local
environment and run:

```sh
python3 scripts/execution_routes.py --check
```

Check mode reports validity without printing configuration values. Do not
commit actual configurations or copy them into public issues, PRs, or logs.

## Selection and Budget Rules

- A system with a configured route uses that route's build/run tags as a pair.
  An incomplete or invalid route is an error, never a fallback to CSV tags.
- An unset file variable preserves CSV runner selection. Systems not listed
  in a valid configuration also retain their existing behavior.
- An omitted or empty `BK_ALLOCATION_PROJECT_ID` uses the route allocation.
  A nonempty pipeline/profile allocation must match it, otherwise matrix
  generation fails before benchmark jobs are submitted.
- `BK_SCHEDULER_EXTRA_ARGS`, the selected system's corresponding override, and
  a preexisting `SCHEDULER_PARAMETERS` cannot be used with a route. Edit the
  route rather than overriding its budget.
- Set `allocation_project_id` to an empty string when no allocation override is
  needed. The key remains required. Generated jobs explicitly bind an empty
  allocation; a nonempty pipeline allocation is still a conflict.
- Nonempty allocation binding currently supports the existing semantic allocation
  adapters: Fugaku/FugakuCN (`-g`) and RIKYU (`--account`). Other systems fail
  closed until an appropriate adapter is available. For a nonempty allocation,
  the queue template must include `${scheduler_extra_args}`. Allocation-free
  routes do not require an allocation adapter or that template placeholder.
- Generated build/run jobs set the resolved allocation for environment
  snapshots, even when an empty allocation was forwarded from the parent.
  `BK_ROUTE_ALLOCATION_PROJECT_ID` is reserved for this handoff.
- A global allocation used with several routed systems must match every
  selected route. Omit it to let each route supply its own budget.
- `BK_EXECUTION_ACTIVITY`, application parameters, and system identity are
  unchanged. Do not derive public responsibility labels from runner accounts.

For legacy profiles, Portal users continue selecting the GitLab target and execution profile.
There is no new per-submit tag selector. A profile may omit its allocation and
use the configured route, or declare a matching allocation. Mismatches are
reported by the matrix generation job; the Portal does not read GitLab project
variables or validate this binding before triggering a pipeline.

## Authentication and Access

The default ID-token audience is the current GitLab server URL. A route may
set `id_token_audience` when the Jacamar configuration requires another value.
The issuer, trusted server, expected token variable (`CI_JOB_JWT` here), and
required audience must agree with the runner configuration. Setting tags does
not change those trust relationships. See the [Jacamar ID-token guide](https://ecp-ci.gitlab.io/docs/guides/id-token-migration.html).

For an unrouted job, the generated audience uses `$CI_SERVER_URL` instead of a
fixed server address. Verify any enforced audience when migrating an existing
runner whose expected audience differs from its GitLab server URL.

These checks prevent configuration mistakes; they are not an authorization
boundary against a user who can edit CI code or override project variables.
Restrict pipeline-variable overrides, runner project scope, and executable
refs according to the site's policy. Protected variables are available only
on eligible refs: if the route file is unavailable, legacy behavior applies.
Configure variable protection and runner/ref access together so a missing file
cannot inadvertently enable an unwanted legacy route.

Keep work directories, writable caches, and credentials separated by execution
account. Build outputs pass through GitLab artifacts; sharing a budget does not
justify widening filesystem permissions. Conversely, sharing a machine does
not make allocations interchangeable.

Route files must contain no credentials. Tags and allocation values occur in
the generated CI artifact and job metadata; control project CI/artifact access
accordingly. They are not automatically public-safe merely because they are
not passwords. The generator does not print their values, and route allocation
is not promoted to a public activity label.
