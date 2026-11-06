"""Classification for explicit preservation of unclassified snapshot files."""

import re
import uuid


def document_file_identity(role, name):
    """Return only an identity declared by a canonical filename, never invent one."""
    prefix = {'results': 'result', 'estimates': 'estimate'}.get(role)
    if prefix is None:
        raise ValueError('Unknown document role')
    match = re.fullmatch(prefix + r'_(\d{8}_\d{6})_([0-9a-f-]{36})\.json', name)
    if not match:
        return None
    stamp, identifier = match.groups()
    try:
        if str(uuid.UUID(identifier)) != identifier:
            return None
    except ValueError:
        return None
    return stamp, identifier
