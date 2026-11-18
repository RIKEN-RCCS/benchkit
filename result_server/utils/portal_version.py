"""Portal release/version helpers."""

from __future__ import annotations

import os


RELEASE_NOTES = [
    {
        "version": "v2026.11.11",
        "date": "2026-11-11",
        "title": "Result discovery and execution tracking",
        "summary": "CX Portal release for November 11, 2026, with improved result discovery and execution tracking.",
        "changes": [
            "Find available benchmark results by system, application and experiment, and retain comparison selections across searches.",
            "Improve Result search and authenticated Usage report responsiveness with a rebuildable index.",
            "Follow execution history and Result/Estimate links, and review estimate version differences in the authenticated Console.",
            "Support Benchpark-backed execution profiles in the authenticated Console.",
            "Add optional site information and clearly separated contact links.",
            "Add opt-in encrypted storage for results, estimates, artifacts, execution profiles, submission history and sign-in state, with snapshot migration and verified recovery.",
        ],
    },
    {
        "version": "v2026.10.15",
        "date": "2026-10-15",
        "title": "Public result browsing updates",
        "summary": "Prepared for the planned public CX Portal release on October 15, 2026.",
        "changes": [
            "Show recorded public activity labels alongside benchmark results.",
            "Update benchmark charts while retaining tabular performance values.",
            "Add system summaries for Flow2 Type I and Type II.",
        ],
    },
    {
        "version": "v2026.08.31",
        "date": "2026-08-31",
        "title": "Initial public CX Portal baseline",
        "summary": (
            "Initial public portal surface with result browsing, comparison, "
            "system information, and release visibility."
        ),
        "changes": [
            "Browse public benchmark results from the portal.",
            "Open public-safe result detail pages.",
            "Compare selected public results.",
            "Browse connected system summaries.",
            "Show the deployed portal version in the shared footer.",
            "Open a public Changes page with broad release notes.",
        ],
    }
]


def portal_version_info(env=None, *, start_path=None):
    """Display administrator-supplied release metadata without invoking Git."""
    import re
    source = os.environ if env is None else env
    value = source.get('RESULT_SERVER_VERSION') or source.get('BENCHKIT_PORTAL_VERSION')
    label = value.strip() if isinstance(value, str) else ''
    commit = source.get('RESULT_SERVER_SOURCE_COMMIT')
    commit = commit.strip() if isinstance(commit, str) else ''
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,79}', label):
        label = 'development'
        name = 'default'
    else:
        name = 'environment'
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
        commit = ''
    return {'label': label, 'commit': commit, 'source': name}


def portal_release_notes() -> list[dict[str, object]]:
    """Return broad-grained release notes for the public changes page."""
    return RELEASE_NOTES
