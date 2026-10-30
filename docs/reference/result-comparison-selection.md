# Result Comparison Selection

Result comparison selection is independent of the current search. Checkboxes
add or remove stored Result filenames in the current browser tab's
`sessionStorage`. Searching, updating candidates, paging, and returning to the
initial query page preserve that selection. Selected Results can be inspected
through detail links, removed individually, or cleared together. Clear page only
removes the current page's rows. All only adds visible rows on the current page.

The key is isolated by the generated comparison URL, so different instance or
public/Console URL prefixes do not share selections. A server-generated scope
also binds it to the login-session nonce, user, visibility mode, and current
affiliations. A scope change resets selection. No Result bodies, FOM values,
credentials, or display metadata are stored. Private filenames remain browser
session data, not a server-side authorization source. Closing the tab normally
ends storage; browser session restoration may restore it. Browser storage is not
an archival or confidentiality boundary.

Storage denial/quota failure falls back to in-page selection and reports the
failure. Malformed stored data is not restored. Selection is not shared across
tabs or devices, and does not automatically submit any request.

Compare still requires at least two selected files and navigates to the existing
GET comparison URL. The existing server rechecks file existence, safe paths,
authentication/confidentiality, and public projection. Deleted or newly private
files can therefore be refused even if previously selected. This UI does not
change comparison evidence, FOM units, scientific compatibility, or existing
chart/ratio behavior. It does not assert that different applications or systems
are comparable. No database schema, ingestion, service, or automatic monitoring
changes are involved.

The list route stores only a random scope nonce in the existing Flask session;
selection itself is browser-only. The nonce is not an authentication credential,
and only an HMAC of the scope is rendered, not the user's email/affiliations or
the signing secret. Existing no-store behavior for All Results is unchanged.

## Tests

```sh
python -B -m pytest -q result_server/tests/test_result_comparison_selection.py
node result_server/tests/test_result_comparison_selection.js
```

The synthetic browser harness verifies cross-query persistence, duplicates,
page-only and whole-selection removal, Back restoration, scope/instance
isolation, invalid storage, and blocked browser storage. Flask fixture tests
verify initial-page access, stable scopes across filters, reset on identity or
affiliation changes, and existing missing/private/unsafe-file rejection. Node is
only a test tool; it is not a server runtime dependency.
