"""Import an explicit execution observation into existing encrypted CX storage."""

import argparse
import json
import os

if __package__:
    from .cx_storage import _private_json
    from .utils.cx_persistence import CxPersistence
    from .utils.execution_evidence import ExecutionEvidenceStore, MAX_BYTES, validate_evidence
else:
    from cx_storage import _private_json
    from utils.cx_persistence import CxPersistence
    from utils.execution_evidence import ExecutionEvidenceStore, MAX_BYTES, validate_evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, help='Private JSON: database, key_file, optional artifact_database')
    parser.add_argument('--input', required=True, help='Private normalized evidence JSON; no logs or credentials')
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        plan = _private_json(args.plan, 65536)
        if not isinstance(plan, dict) or not {'database', 'key_file'} <= plan.keys() or plan.keys() - {'database', 'key_file', 'artifact_database'}:
            raise ValueError('Invalid plan')
        if any(not isinstance(p, str) or not os.path.isabs(p) for p in plan.values()):
            raise ValueError('Absolute paths required')
        observation = validate_evidence(_private_json(args.input, MAX_BYTES))
        persistence = CxPersistence.open_existing(plan['database'], plan['key_file'], artifact_path=plan.get('artifact_database'))
        changed = ExecutionEvidenceStore(persistence).import_observation(observation)
        print(json.dumps({'status': 'success', 'changed': changed}))
        return 0
    except Exception:
        print(json.dumps({'status': 'failed', 'retry_performed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
