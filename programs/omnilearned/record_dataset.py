"""Publish only complete staged observations, or an explicit unavailable record."""

import json
import os
from pathlib import Path
import sys
import tempfile


def publish(staging, reason, source, destination):
    data = json.loads(destination.read_text()) if destination.exists() else {"schema_version": 1, "inputs": []}
    if not isinstance(data, dict) or not isinstance(data.get("inputs"), list):
        raise ValueError("invalid input metadata")
    if reason:
        items = [{"dataset_id": "omnilearned-top-staged", "kind": "pre-staged-input",
                  "source": "site-local", "collection_status": "unavailable",
                  "collection_error": reason, "verification_status": "unavailable",
                  "recipe": "Staged dataset at {}; contents not read ({})".format(source, reason)}]
    else:
        observed = json.loads((Path(staging) / "input_info.json").read_text())
        items = observed["inputs"]
        if not isinstance(items, list) or not items:
            raise ValueError("missing observation")
    data["inputs"].extend(items)
    fd, name = tempfile.mkstemp(prefix=".omni-input-publish-", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, sort_keys=True)
            output.write("\n")
        os.replace(name, str(destination))
    finally:
        if os.path.exists(name):
            os.unlink(name)


if __name__ == "__main__":
    try:
        publish(sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        print("OmniLearned: dataset observation could not be stored", file=sys.stderr)
        sys.exit(1)
