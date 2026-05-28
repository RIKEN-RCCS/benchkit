"""Admin route policy helpers."""

from __future__ import annotations

import re

_CONTROL_CHARS = frozenset(chr(code) for code in range(32)) | {chr(127)}
_AFFILIATION_DELIMITERS = frozenset({","})
_EMAIL_MAX_LEN = 254
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PATH_CHARS = frozenset({"/", "\\"})
_UNSAFE_EMAIL_CHARS = frozenset({"<", ">", '"', "'", " ", "\t", "\n", "\r", "\\", "`"})


def parse_allowed_affiliations(value: str | None) -> frozenset[str] | None:
    """Parse an optional comma-separated affiliation allowlist."""
    if value is None:
        return None
    if not value.strip():
        return None
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def is_valid_email(value: str) -> bool:
    """Return whether a portal user email is safe and well formed."""
    if not isinstance(value, str):
        return False
    email = value.strip()
    if not (1 <= len(email) <= _EMAIL_MAX_LEN):
        return False
    if any(char in _UNSAFE_EMAIL_CHARS for char in email):
        return False
    return bool(_EMAIL_RE.fullmatch(email))


def _is_safe_affiliation_name(value: str) -> bool:
    """Return whether a user-managed affiliation name is safe to store."""
    if not value or value in {".", ".."}:
        return False
    blocked_chars = _CONTROL_CHARS | _AFFILIATION_DELIMITERS | _PATH_CHARS
    return not any(char in blocked_chars for char in value)


def parse_affiliations(
    value: str,
    allowed: set[str] | frozenset[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Parse, deduplicate, and validate submitted affiliations."""
    affiliations: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for item in value.split(","):
        affiliation = item.strip()
        if not affiliation:
            continue
        if affiliation in seen:
            continue
        seen.add(affiliation)
        if not _is_safe_affiliation_name(affiliation):
            invalid.append(affiliation)
            continue
        if allowed is not None and affiliation not in allowed:
            invalid.append(affiliation)
            continue
        affiliations.append(affiliation)

    return affiliations, invalid
