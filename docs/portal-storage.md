# Optional storage modes

The default configuration remains supported. The additional modes are opt-in.

Read-only exports provide filtered result documents and a derived catalog.
Catalog readers reject writes, and the application limits accepted requests.

The access-policy setting is optional. Its absence preserves the existing
checks. A configured policy must be owned by the administrator.

Deployment configuration, credentials, databases, and application state are
managed outside the source tree. Package the complete committed tree when
preparing a release, including its configuration data and static assets.

Validate search results, detail links, and populated system listings from the
packaged release. A successful page response alone does not establish that its
required data is present.

## Reviewed public exports

Public export requires an explicit disclosure policy. Each approved document
binds a source digest to the exact selected values. Changed sources require
review again. Archive approval additionally selects individual regular-file
members by name and digest. The exporter rebuilds archives from those members
and normalizes their metadata. An empty policy publishes no result content.

Publication withdraws the previous generation before applying the supplied
source-change callback. A failed build stays withdrawn. Rebuilding uses the
current source and approvals. Retired generations are removed immediately.
The ceilings are two generations, fifteen minutes and 256 MiB of generation
content, including the derived catalog and temporary build files.

A trusted supervisor is required. It must stop the complete reader process
group and outstanding responses within five seconds, supervise the build
independently, and run expiry cleanup even if the publisher exits. Removing
file permissions alone leaves already-open descriptors usable. The supervisor
must also bound reader lifetime at the publication deadline. All changes that
withdraw public access must pass through this publication boundary.

`SystemdPublicationControl` connects the publisher to independent transient
systemd lease and reader services. The writer runs in a dedicated management
service. The adapter currently requires a privileged management context. Its
code, interpreter and private registry must be administrator-controlled. Public
HTTP input must never choose commands, paths, identities or service names.

Each reader has a distinct UID and a control-group lifetime bound to its lease
service. An abnormal lease-service exit triggers stop-post cleanup. The watcher
also detects incomplete writer exit and reader exit. Expiry stops the writer
before acquiring its publication lock, so a hung build cannot block retirement.
Generation tokens prevent an old cleanup from withdrawing a renewed generation.
The writer marks completion only after publication state is durable.

The opt-in acceptance tests use real transient services, a synthetic encrypted
DB, a loopback HTTP server and a separate reader UID. They cover open-file
streams, descendants in different process groups, writer and reader crashes,
supervisor termination, build timeout, lease expiry and generation renewal.
The copy fixture disables Redis connections. Production identities, SELinux,
mounts, proxy integration and manager startup recovery require deployment
acceptance before this adapter is used outside the isolated test environment.

## Version metadata and repository trust

The footer reads reviewed release metadata from `RESULT_SERVER_VERSION` (or
`BENCHKIT_PORTAL_VERSION`) and optional `RESULT_SERVER_SOURCE_COMMIT`. It invokes
no Git commands. Invalid labels use the default label and invalid commits are
omitted.

Version comparison requires an explicitly trusted repository location. The
repository, its ancestors and Git metadata must satisfy owner and write-mode
checks before Git runs. Unsupported metadata layouts and configuration includes
produce an unavailable version result. Service configuration must select the
trusted location and owner as part of its separate deployment review.

### Automatic publication after ingest

For the encrypted ingest service, set `RESULT_SERVER_PUBLICATION_QUEUE` to a
private, shared notification directory. Successful Result and measurement
artifact receipts create a coalescing pending marker after saving the input.
Configure a path unit with PathExists conditions on both `pending` and
`publishing` in that directory. Its one-shot service invokes
`python -m utils.public_events CONFIG`. Use a unique writer service for this
installation. An interrupted publication retains the working marker for retry.
A storage commit and a filesystem notification are separate operations. A
reconciliation job can enqueue a rebuild after an unclean ingest shutdown.

The administrator-owned JSON configuration supplies the queue directory,
encrypted store constructor arguments, supervisor arguments and a
`benchmarks` object keyed by benchmark code. Missing optional rules omit the
corresponding fields. Each benchmark may define public repositories and refs,
known public file checksums, allowed profile values by field, build tools,
compiler/MPI/package versions, scalar metric names and a numeric vector layout.
Activity and the standard public Result fields are automatically projected.
Keep configuration, registry and command selection outside the ingest and
reader identities' write permissions.

For PA output, map a known archive basename under `pa` to a registered CSV
member name and a list of numeric columns. Only matching references on a
public Result are considered. The exporter reconstructs the download from
finite numeric values and uses the registered basename for the public link.
Unsupported formats remain private. The opt-in systemd acceptance test
contains a working configuration with synthetic data.

#### Receipt responses and rebuilding a missing publication

HTTP 200 for a Result or PA upload confirms storage. Keep the returned ID,
timestamp and filename. With the queue configured, `publication_notification`
is `queued` when the marker was created, or `failed` when storage succeeded
and the notification operation raised an OS error. Both responses acknowledge
one saved upload. Continue using its receipt and do not post it again to
trigger publication. With the queue disabled the existing response is unchanged.
A lost connection before the response leaves receipt status unknown. Check the
saved store before considering any retry. Result submission allocates a new ID
and replaying the same submission can create a duplicate.
The sender skips malformed artifact references and continues with valid ones.
If a PA response is lost after Result acceptance, the sender stops and reports
the accepted Result ID. Use that ID to check whether the PA was stored.

An administrator with read access to CONFIG and write access to its queue can run
`python -m utils.public_events --request-rebuild CONFIG` to enqueue a complete
projection of the saved store. This also recovers receipts committed before the
ingest process died without sending a notification. The command prints `queued`.
The configured path unit or trusted one-shot worker must process the marker.
The worker prints `published` on completed publication, `busy` on contention,
and `idle` when there is no work. Verify the current generation and expected
public content. Repeating the request may rotate the public generation, but
writes no input records and creates no duplicate Result or PA entry. Invalid
optional file references are skipped individually while valid siblings and
other Results continue through publication.
