"""Security metadata routes for vulnerability reporting and crawler hints."""

from flask import Response


SECURITY_TXT = """Contact: https://github.com/RIKEN-RCCS/benchkit/security/advisories/new
Expires: 2027-05-19T00:00:00Z
Preferred-Languages: ja, en
Canonical: https://fncx.r-ccs.riken.jp/.well-known/security.txt
Policy: https://github.com/RIKEN-RCCS/benchkit/blob/main/SECURITY.md
"""

ROBOTS_TXT = """User-agent: *
Disallow: /admin/
Disallow: /auth/
Disallow: /dev/admin/
Disallow: /dev/auth/
"""


def register_security_metadata_routes(app, prefix=""):
    """Register RFC 9116 security.txt and robots.txt routes."""
    endpoint_prefix = (
        "security_metadata"
        if not prefix
        else f"security_metadata_{prefix.strip('/').replace('/', '_')}"
    )

    @app.route(
        f"{prefix}/.well-known/security.txt",
        endpoint=f"{endpoint_prefix}_security_txt",
    )
    def security_txt():
        return Response(SECURITY_TXT, mimetype="text/plain")

    @app.route(f"{prefix}/robots.txt", endpoint=f"{endpoint_prefix}_robots_txt")
    def robots_txt():
        return Response(ROBOTS_TXT, mimetype="text/plain")
