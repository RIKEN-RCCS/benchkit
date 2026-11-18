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
