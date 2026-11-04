"""Combine aligned component predictions without app-specific kernel semantics."""
import hashlib
import json
from pathlib import Path
import re


def combine_predictions(directory, count, package, version, model_name):
    directory = Path(directory)
    results = [json.loads((directory / f'kernel_{i}.json').read_text()) for i in range(count)]
    if not results or any(r['package_applicability']['status'] != 'applicable'
            or r['model']['version'] != version or len(r['metrics']['kernels']) != 1 for r in results):
        raise ValueError('Require applicable, aligned component predictions')
    commits = {r['model']['provenance']['external_commit'] for r in results}
    if len(commits) != 1 or not re.fullmatch(r'[0-9a-f]{40}', next(iter(commits))):
        raise ValueError('Require one resolved model commit across predictions')
    for result in results:
        provenance = result['model']['provenance']
        if hashlib.sha256(Path(provenance['manifest']).read_bytes()).hexdigest() != provenance['sha256']:
            raise ValueError('Prediction provenance manifest changed')
    return dict(estimation_package=package,
        model=dict(name=model_name, version=version, external_commit=next(iter(commits)),
                   component_provenance=[r['model']['provenance'] for r in results]),
        component_results=[dict(path=str(directory / f'kernel_{i}.json'),
            sha256=hashlib.sha256((directory / f'kernel_{i}.json').read_bytes()).hexdigest())
            for i in range(count)],
        metrics=dict(kernels=[r['metrics']['kernels'][0] for r in results]))
