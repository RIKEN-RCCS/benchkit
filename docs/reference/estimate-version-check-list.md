# Version Check List

Authenticated users can open **Version Checks** from Estimated Results or from
an Estimate's Version Check details. The list compares recorded method and
package versions against the operator-configured local repository/ref. It is
absent from public surfaces and does not grant access to additional records.

The default filter is **Version differences**. Other filters are **Unknown**,
**Recorded versions match**, and **All**, optionally restricted by application.
Each entry links to the Estimate detail and its Estimation History, and shows
the source Result UUID, recorded system/node conditions, and difference/unknown
counts. Historical and branching Estimates are not automatically collapsed.

- Resolve the configured ref once per list request, then compare every visible
  selected record against that commit. A subsequent request may resolve a newer
  commit; the reference used for that request is displayed.
- Apply classification and filtering before pagination. Counts include only
  accessible records for the selected application, before the status filter.
- **Version differences** can coexist with unknown components. It does not mean
  a version is newer, an old Estimate is invalid, or re-estimation is required.
- **Recorded versions match** concerns only comparable explicit records. It is
  not a claim that every dependency or external model is current.
- Missing records or declarations stay unknown. External model versions are
  not inferred from package versions. Unavailable/invalid refs do not fall back
  to another checkout or branch.
- Query parameters cannot select a repository/ref. Missing operator settings
  show a disabled state without reading Git or stored Estimates.
- Unreadable/invalid JSON produces an incomplete-list notice. Symlinks are not
  followed. Existing file confidentiality checks apply before classification.

This is an on-demand, read-only view of existing JSON and local Git objects.
It does not fetch refs, execute estimator/package code, write an index or DB,
change a schema, notify users, or start CI, profiling, or re-estimation.
