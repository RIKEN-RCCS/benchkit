# Scheduled submission reconciliation

An interrupted trigger request may have created a pipeline despite losing its
response. Absence from a search never proves rejection and must not authorize a
retry. The existing runner continues holding these attempts.

`utils.submission_reconciliation` adds a backend-only inspection and explicit
accepted-only confirmation boundary. It is not wired into the runner, timers,
management UI or a command-line entry point. No database migration is needed.

The caller supplies a saved row, a trusted configured target, and a read-only
reader. The reader implements `pipelines(target, ref, page)` returning
`PipelinePage`, `project_path(target, project_id)` returning the project path
from independently retrieved project identity, and `variables(target, id)`
returning the complete key/value list. It must use the configured target host,
reject redirects, and raise on HTTP, authentication, parsing or pagination
uncertainty. `GitLabReadOnlyReader` supplies a GET-only transport with explicit read
credentials, a pinned target, redirect rejection, bounded responses and timeouts.
Trigger tokens are not read credentials; no token discovery is performed.
It is tested with a fake opener only and is never invoked by the runner.
The relevant upstream API is documented in the
[GitLab pipelines API](https://docs.gitlab.com/api/pipelines/).

Only non-dry-run scheduled `submission_unknown` rows with a timed reason are
eligible. Project, target, request URL, ref, trigger identity, slot, backend and
all saved request variables must agree. Missing variables, malformed responses,
unresolved project identity, incomplete pagination, no candidates and multiple
candidates keep the attempt held. The default page limit is ten; the reader
must positively report the last page. Repeated pipeline IDs are treated as an
unstable enumeration and held. This is conservative evidence inspection, not a
transactional snapshot of the remote service.

`inspect_submission` never writes. `confirm_submission` fetches evidence again
and only changes the exact unchanged saved row to `submitted`, storing the
pipeline ID and preserving the original submit response and error list. It
cannot mark an attempt rejected, release a hold for retry, or submit a pipeline.
Concurrent edits reject confirmation. Legacy ambiguous failures and interrupted
`submitting` rows remain held pending a separate policy; no automatic timeout
or state conversion is introduced.

Validation uses fake readers and temporary SQLite databases for both existing
Benchkit and Benchpark runner payloads. Production transport, real database
confirmation and live acceptance remain outside this local validation.
