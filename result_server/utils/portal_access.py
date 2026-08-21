"""Route access classification for CX Portal deployment policy."""

from __future__ import annotations

from flask import abort, request


ACCESS_PUBLIC = "public"
ACCESS_PUBLIC_CONDITIONAL = "public_conditional"
ACCESS_RESTRICTED_VIEWER = "restricted_viewer"
ACCESS_AUTHENTICATED_CONSOLE = "authenticated_console"
ACCESS_OPERATOR = "operator"
ACCESS_RUNNER_API = "runner_api"

ACCESS_CLASSES = {
    ACCESS_PUBLIC,
    ACCESS_PUBLIC_CONDITIONAL,
    ACCESS_RESTRICTED_VIEWER,
    ACCESS_AUTHENTICATED_CONSOLE,
    ACCESS_OPERATOR,
    ACCESS_RUNNER_API,
}

PUBLIC_ENDPOINTS = frozenset(
    {
        "home",
        "systemlist",
        "static",
        "results.results",
    }
)

PUBLIC_CONDITIONAL_ENDPOINTS = frozenset(
    {
        "results.result_compare",
        "results.result_detail",
        "results.show_result",
    }
)

RESTRICTED_VIEWER_ENDPOINTS = frozenset(
    {
        "auth.login",
        "auth.logout",
        "auth.setup",
        "estimated.estimated_detail",
        "estimated.estimated_results",
        "estimated.show_estimated_result",
        "results.environment_snapshot_results",
        "results.results_confidential",
    }
)

AUTHENTICATED_CONSOLE_ENDPOINT_PREFIXES = ("profile_requests.",)
OPERATOR_ENDPOINT_PREFIXES = ("admin.",)
OPERATOR_ENDPOINTS = frozenset({"results.usage_report"})
RUNNER_API_ENDPOINT_PREFIXES = ("api.",)
PUBLIC_ENDPOINT_PREFIXES = ("security_metadata",)
PUBLIC_PORTAL_ALLOWED_ACCESS_CLASSES = frozenset(
    {
        ACCESS_PUBLIC,
        ACCESS_PUBLIC_CONDITIONAL,
        ACCESS_RUNNER_API,
    }
)


def is_public_portal_mode(value) -> bool:
    """Return whether a config/env value enables the public portal surface."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def classify_endpoint(endpoint: str) -> str | None:
    """Return the deployment access class for a Flask endpoint."""
    if endpoint in PUBLIC_ENDPOINTS or endpoint.startswith(PUBLIC_ENDPOINT_PREFIXES):
        return ACCESS_PUBLIC
    if endpoint in PUBLIC_CONDITIONAL_ENDPOINTS:
        return ACCESS_PUBLIC_CONDITIONAL
    if endpoint in RESTRICTED_VIEWER_ENDPOINTS:
        return ACCESS_RESTRICTED_VIEWER
    if endpoint in OPERATOR_ENDPOINTS or endpoint.startswith(OPERATOR_ENDPOINT_PREFIXES):
        return ACCESS_OPERATOR
    if endpoint.startswith(AUTHENTICATED_CONSOLE_ENDPOINT_PREFIXES):
        return ACCESS_AUTHENTICATED_CONSOLE
    if endpoint.startswith(RUNNER_API_ENDPOINT_PREFIXES):
        return ACCESS_RUNNER_API
    return None


def is_endpoint_allowed_in_public_portal(endpoint: str | None) -> bool:
    """Return whether an endpoint may be reached when public portal mode is on."""
    if not endpoint:
        return False
    access_class = classify_endpoint(endpoint)
    return access_class in PUBLIC_PORTAL_ALLOWED_ACCESS_CLASSES


def register_public_portal_guard(app):
    """Install a Flask allowlist guard for public portal deployments."""

    @app.before_request
    def enforce_public_portal_allowlist():
        if not app.config.get("PUBLIC_PORTAL_MODE", False):
            return None
        if is_endpoint_allowed_in_public_portal(request.endpoint):
            return None
        abort(404)
