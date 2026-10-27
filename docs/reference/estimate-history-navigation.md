# Estimate History Navigation

Authenticated Result and Estimate detail pages show the accessible Estimates
whose recorded source Result UUID matches. Each entry links to its detail page,
shows its recorded conditions, method/package versions and applicability, and
links to its previous Estimate when that reference resolves unambiguously.
Estimate details also link back to an accessible source Result. The selected
Estimate is highlighted; subsequent estimates, including branches, remain in
the same table.

The table reads the existing stored JSON files. It does not migrate a database,
rewrite metadata, poll CI, trigger estimation, or designate a latest/best result.
Timestamp ordering is only for display and never establishes parentage.

- Parent references come from `reestimation.previous_estimation_result_uuid`,
  `source_estimate_result_uuid`, or `source_estimate.uuid`; conflicting references
  do not create a parent link.
- A missing parent reference means **No parent recorded**, not proof that the
  record is an initial Estimate.
- Missing, inaccessible, ambiguous, cross-source, or cyclic parents are not
  linked. Duplicate Estimate UUIDs are not resolved by choosing a file.
- Explicit condition overrides are identified when recorded in
  `reestimation.resolved_request.explicit_changes`. Unknown versions remain
  unknown, and differing conditions do not invalidate an Estimate.
- This navigation is absent from public surfaces and unauthenticated pages.
  Linked records retain the existing detail-page confidentiality checks.
- Invalid/unreadable JSON files produce an incomplete-history notice rather
  than a claim that all estimates have been found. Symlinks are not followed.

Coverage is limited to the instance's currently stored, accessible JSON files;
no links or record counts from other instances or inaccessible records are shown.
