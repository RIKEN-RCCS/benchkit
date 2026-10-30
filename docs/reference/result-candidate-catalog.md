# Result Candidate Catalog

The optional candidate catalog is a derived index of stored Result JSON files.
It supplies actual System / Application / Experiment combinations and counts
before a user requests Result rows. Usage aggregation remains independent.
No Result, Estimate, Profile, Budget, or Runner database schema is changed.

## Identity and Visibility

- One JSON basename is one stored Result, matching the existing list loader.
  Replacing the same basename replaces its old contribution; repeating it does
  not increment the count. The receiver can store multiple files with the same
  UUID at different timestamps. These remain separate stored records, not a
  deduplicated count of scientific experiments.
- Group counts are maintained by System, Application, Experiment, and normalized
  confidentiality tags. No FOM, credentials, full JSON, or artifact contents are
  copied into the catalog. Unknown names and missing fields do not reject receipt.
  Missing/non-string dimensions appear as `Not recorded`, without an exact-tuple
  View link. They still contribute to the visible total.
- Public Results only count public files, even for logged-in administrators.
  All Results requires authentication and counts public files plus files sharing
  at least one current affiliation; administrators can see all. Matching multiple
  tags never double counts. Hidden tuples and hidden counts are not returned.
- Facets exclude their own current filter, applying the other dimensions. Tuple
  rows apply all filters and are paged (50 combinations per page). `Update
  candidates` and candidate paging only query the catalog, not Result files.
  Each candidate dimension is a native select with an All option, so an existing
  selection can be changed without deleting text. A current value absent from
  the candidates remains selected without an invented count. When the catalog
  is disabled or unavailable, text inputs remain available for manual queries.
  Search and View remain explicit Result queries, using the existing loader and
  its visibility checks. Counts are a request snapshot, not a search guarantee
  against concurrent receipt or removal.

## Explicit Lifecycle

The default is disabled. To opt in, all receiver and Web processes for a Result
directory must use the same `RESULT_SERVER_RESULT_CATALOG_PATH`. It resolves to
Flask `RESULT_CATALOG_PATH`. The catalog lives in a separate directory owned by
the application user with mode 700; catalog/lock/journal files require mode 600.
Do not place it inside received Results or under a served/downloadable root.
This metadata store uses standard SQLite, **not encryption**. It must be protected
like confidential metadata. Encrypted authoritative storage is a separate future
migration, not a claim made by this index.

Before enabling catalog-aware writers, an operator explicitly initializes and
rebuilds it, with all writers to that Result directory quiesced:

```sh
python -B scripts/result_catalog.py --results /private/results \
  --catalog /private/catalog/candidates.sqlite3 --initialize
```

Rebuild an existing catalog with the same command without `--initialize`.
The command reads source JSON, modifies only the derived catalog and lock, and
does not display individual records or paths on failure. It neither starts a
service nor rewrites Results. Creation never replaces an existing catalog.
An incomplete initial catalog remains unavailable until a successful rebuild.
Malformed/non-object JSON, symlinks, and unreadable files abort rebuilding and
leave the catalog unavailable, rather than treating those files as public/zero.

Catalog-aware receipt holds one interprocess writer lock across JSON atomic
replacement and the differential count update. It first commits `ready=0`, then
syncs the source directory and publishes the updated entries/counts and readiness
in one transaction. Readers
use a read-only SQLite snapshot and refuse dirty catalogs. Rebuild uses the same
lock and publishes a complete replacement transaction. Busy writers are not
retried automatically. A failed/crashed update leaves the durable dirty flag;
ordinary incremental updates cannot clear an incomplete baseline. A complete
rebuild is required.

If catalog publication fails, the receiver returns a generic 503. The JSON may
already have been atomically saved; do not blindly retry or assume no data was
stored. Inspect receipt history and rebuild first. Storage unavailable before
invalidation prevents the JSON write. This is an opt-in storage consistency
contract, not rejection of changed scientific inputs. Disabled behavior is
unchanged, and Estimate ingestion does not update this Result-only catalog.

`ResultCatalog.delete` is an internal callback-based lifecycle hook, not a new
HTTP deletion endpoint. Participating replacement/deletion writers must use the
same lock/invalidation contract. Existing receipt is integrated; out-of-band
edits, imports, removals, or old receivers that bypass it are **not watched**.
Quiesce writers and rebuild after such operations, and do not advertise the old
catalog during them. Mixed old/new writer deployment is unsupported. A GET never
rebuilds, initializes, scans Result JSON, or silently falls back to hidden totals.
If unavailable, the page shows that state and keeps manual Search available.

## Local Tests

```sh
python -B -m pytest -q result_server/tests/test_result_catalog.py \
  result_server/tests/test_result_catalog_routes.py \
  result_server/tests/test_explicit_result_queries.py
```

Tests use synthetic data and disposable databases: idempotent replacement,
visibility changes/removal, independent UUID/file identity, permission parity,
contextual facets/paging, failed publication/rebuild, writer exclusion, private
permissions, escaping, actual ingestion routing, and no-scan initial/candidate
views. No deployment, live database operation, or CI invocation is implied.
