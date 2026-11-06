"""Unambiguous JSON parsing at document write boundaries."""

import json


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            # Neither field names nor values belong in client errors or logs.
            raise ValueError("Duplicate JSON object member")
        result[key] = value
    return result


def load_document_json(raw):
    """Reject duplicate members, including equal values and nested objects.

    Existing stored documents remain readable. This is a write-boundary check,
    not an implicit repair of legacy data or a change to numeric decoding.
    """
    return json.loads(raw, object_pairs_hook=_unique_pairs)
