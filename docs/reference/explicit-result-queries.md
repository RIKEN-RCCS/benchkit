# Explicit Result Queries

Results and All Results initially show a search form without scanning stored
Result files. Search submits `search=1`, the application, system, experiment,
and page size. Empty target fields mean all values. Without the optional
[candidate catalog](result-candidate-catalog.md), suggestions come from repository
definitions and an unlisted target may be typed explicitly. With the catalog,
permission-filtered stored combinations and counts populate select controls.
Update candidates queries only that catalog, not Result files.

Existing URLs containing application/system/experiment or paging parameters
continue to execute a search. Page links and page-size changes retain the
selected targets. Results are still restricted by their public/confidential
tags and the current session's affiliations. Display rows are constructed only
after filtering and pagination. Detail and comparison routes are unchanged.
[Comparison selection](result-comparison-selection.md) can be retained across
searches in the same browser tab without loading all Results.

Usage initially shows only report and target controls. Aggregate submits
`run=1`; only the selected report is built. Reports are node-hours, profile
operations, performance telemetry, evidence, and configuration checks.
Existing period/target query URLs remain executable. Changing a form field
alone does not send a request. Clear returns to the unexecuted form.

Data reports use the selected fiscal year (April through March), optional month
(`YYYY-MM`) or half (`H1`/`H2`), application, and system. Bounds use dates parsed
from the stored filenames, consistent with the existing usage accounting.
Undated records cannot establish membership in the requested period and are
not included. Estimate system selection refers to its recorded current system.
Evidence output rows and CSV use the same selected scope. Configuration checks
describe repository definitions, not historical executions; period controls do
not turn them into historical configuration snapshots. Profile and trigger
definitions and latest trigger observations remain current state, while their
received Result counts and node-hours use the selected period.

These query controls avoid work on initial navigation. The optional catalog is
a persistent derived candidate index, not an encrypted authoritative Result
database or background job. Explicit searches and reports can still scan the
stored directory. Future query indexing and database
migration must preserve authorization, update/delete semantics and the ability
to reconcile stored records. No schema or deployment configuration changes are
required by these query controls.
