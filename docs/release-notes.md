# Benchkit Release Notes

## v2026.08.31 - Initial public CX Portal baseline

Public portal baseline for scoped QWS measurements on Fugaku and RIKYU, with
public-safe result pages and Portal-managed main-branch triggers.

- Public result browsing, comparison, and system catalog pages are available in
  public portal mode.
- Public mode hides operator-only views, raw result JSON routes, trigger
  internals, and environment snapshot detail.
- Portal-managed triggers submit scoped main-branch measurements with an
  explicit result-server destination.
- Build cache restore checks source identity, host build environment, and
  restored artifact integrity.
- Branch and tag source inputs record the resolved commit used for the build.
- Manual GitLab CI is reserved for development and release-candidate validation,
  not production main results.
