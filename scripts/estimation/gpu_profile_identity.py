"""Keep observed GPU identity distinct from the specifications used by a model."""
import csv


def profile_identity(candidate):
    metrics = candidate.get('metrics', {})
    source_gpus = metrics.get('source_gpus', [])
    if not source_gpus:
        return None
    observed = set()
    for artifact in candidate.get('artifacts', []):
        if artifact.get('kind') != 'gpu_lightgbm_input_csv':
            continue
        try:
            with open(artifact.get('path') or '', newline='') as handle:
                observed.update(row['device__attribute_display_name'] for row in csv.DictReader(handle)
                                if row.get('device__attribute_display_name') not in (None, '', 'nan'))
        except (OSError, csv.Error, UnicodeError):
            pass
    return dict(package=candidate.get('estimation_package'),
                observed_profile_gpu_names=sorted(observed), model_source_gpu_names=source_gpus,
                specification_mapping=('gh200_using_h100_specifications' if 'H100' in source_gpus
                    and any('GH200' in name for name in observed)
                    else 'unverified' if observed else 'unknown'))
