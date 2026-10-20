"""Validate opt-in, deployment-owned text and links for the public surface."""

import json
import os
from urllib.parse import urlsplit


SETTING = "RESULT_SERVER_PUBLIC_SITE_INFO"
MAX_CONFIG_BYTES = 65536
_FIELDS = {"title", "operator", "paragraphs", "contact", "terms", "acknowledgements"}


def _invalid():
    # Configuration text can contain private mistakes; never echo it in errors.
    return ValueError(f"{SETTING} must contain valid public text and HTTPS links")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise _invalid()
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise _invalid()
    return value.strip()


def _paragraphs(value):
    if not isinstance(value, list) or len(value) > 32:
        raise _invalid()
    result = [_text(item, 8192) for item in value]
    if any(not item for item in result):
        raise _invalid()
    return result


def _link(value):
    if not isinstance(value, dict) or set(value) != {"label", "url"}:
        raise _invalid()
    label = _text(value["label"], 256)
    url = _text(value["url"], 2048)
    if not label or not url or any(char.isspace() or ord(char) < 32 or char == "\\" for char in url):
        raise _invalid()
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or "%" in parsed.netloc
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise _invalid()
    except ValueError:
        raise _invalid() from None
    return {"label": label, "url": url}


def parse_public_site_info(raw):
    """Return only explicitly public fields; do not fetch links or read files."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise _invalid()
    try:
        if len(raw.encode("utf-8")) > MAX_CONFIG_BYTES:
            raise _invalid()
        if not raw.strip():
            return None
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) - _FIELDS:
            raise _invalid()
        result = {
            "title": _text(data.get("title", "About this data"), 128),
            "operator": _text(data.get("operator", ""), 256),
            "paragraphs": _paragraphs(data.get("paragraphs", [])),
            "acknowledgements": _paragraphs(data.get("acknowledgements", [])),
            "contact": _link(data["contact"]) if "contact" in data else None,
            "terms": _link(data["terms"]) if "terms" in data else None,
        }
        if not result["title"]:
            raise _invalid()
        return result if any(result[key] for key in _FIELDS - {"title"}) else None
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise _invalid() from None


def configure_public_site_info(app, env=None):
    source = os.environ if env is None else env
    app.config["PUBLIC_SITE_INFO"] = parse_public_site_info(source.get(SETTING))
