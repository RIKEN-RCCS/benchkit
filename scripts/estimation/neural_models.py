#!/usr/bin/env python3
"""Neural release contracts shared by execution, validation and provenance."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re

PACKAGE_DIR = Path(__file__).resolve().parent / 'section_packages'

@dataclass(frozen=True)
class NeuralRelease:
    key: str
    package: str
    family: str
    entry: str
    release: str
    core: str
    label: str
    seeds: int
    spec_sheet: str
    input_generator: str
    trust_anchor: bool
    environment_prefixes: tuple

    def dependencies(self):
        family, release = self.family, self.release
        files = [f'{family}/{self.entry}', f'{family}/network.py', f'{family}/{self.core}',
                 f'{family}/data_pipeline_v2.py', f'{family}/{release}/meta.pkl',
                 f'{family}/{release}/runtime_inputs_training.csv', self.input_generator, self.spec_sheet]
        files += [f'{family}/{release}/model_seed{i}.pt' for i in range(self.seeds)]
        if self.trust_anchor:
            files += [f'{family}/{release}/trust_anchor.json']
        return files

    def validate(self, root):
        root = Path(root).resolve()
        missing = []
        for name in self.dependencies():
            path = root / name
            if not path.is_file():
                missing.append(name)
            elif path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Model dependency escapes the checkout: ' + name)
        if missing:
            raise ValueError('Current PerfTools model dependencies are missing: ' + ', '.join(missing))
        actual = {p.name for p in (root / self.family / self.release).glob('model_seed*.pt')}
        expected = {f'model_seed{i}.pt' for i in range(self.seeds)}
        if actual != expected:
            raise ValueError('Unexpected model seed files for ' + self.key)


def releases():
    models = {}
    for path in sorted(PACKAGE_DIR.glob('*.metadata.json')):
        data = json.loads(path.read_text())
        spec = data.get('neural_release')
        if spec is None:
            continue
        key, package = spec['key'], data['name']
        if not re.fullmatch(r'[a-z][a-z0-9]+', key) or key in models:
            raise ValueError('Invalid or duplicate neural release key')
        for value in (package, spec['family'], spec['entry'], spec['release'], spec['core']):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', value) or value in ('.', '..'):
                raise ValueError('Invalid neural release component')
        for name in ('spec_sheet', 'input_generator'):
            value = spec[name]
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', value) or value.startswith('/') or '..' in value.split('/'):
                raise ValueError('Invalid neural dependency path')
        if type(spec['seeds']) is not int or not 1 <= spec['seeds'] <= 32 or type(spec['trust_anchor']) is not bool:
            raise ValueError('Invalid neural release artifact declaration')
        prefixes = spec['environment_prefixes']
        if (not isinstance(prefixes, list) or not prefixes or any(
                not isinstance(p, str) or not re.fullmatch(r'BK_GPU_[A-Z0-9_]+', p) for p in prefixes)
                or len(prefixes) != len(set(prefixes))):
            raise ValueError('Invalid neural environment prefixes')
        if data['models']['section']['version'] != spec['release']:
            raise ValueError('Package and neural release versions disagree')
        models[key] = NeuralRelease(key, package, spec['family'], spec['entry'], spec['release'], spec['core'],
                                   spec['label'], spec['seeds'], spec['spec_sheet'], spec['input_generator'],
                                   spec['trust_anchor'], tuple(prefixes))
    return models


MODELS = releases()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--root')
    args = parser.parse_args()
    model = MODELS[args.model]
    if args.root:
        model.validate(args.root)
    print(json.dumps({'key': model.key, 'package': model.package, 'environment_prefixes': model.environment_prefixes,
                      'family': model.family, 'release': model.release, 'seeds': model.seeds}))


if __name__ == '__main__':
    main()
