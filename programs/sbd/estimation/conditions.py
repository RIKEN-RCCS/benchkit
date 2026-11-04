"""Recorded conditions for the Davidson method, including its legacy Estimates."""

def recorded_conditions(source):
    projection = ((source.get('future_system', {}).get('model') or {}).get('projection') or {})
    if projection.get('method') != 'sbd-davidson-nsys-weighted-v1':
        return {}, {}
    values = {}
    for side in ('current', 'future'):
        package = source.get('estimate_metadata', {}).get(side + '_package', {})
        values['BK_ESTIMATION_' + side.upper() + '_PACKAGE'] = package.get('estimation_package')
    values.update({
        'BK_GPU_LIGHTGBM_SOURCE_GPU': projection.get('source_gpu'),
        'BK_GPU_LIGHTGBM_TARGET_GPU': projection.get('target_gpu'),
        'BK_GPU_LIGHTGBM_PERFTOOLS_COMMIT': projection.get('prediction_model', {}).get('external_commit'),
    })
    types = {key: ('commit' if key.endswith('_COMMIT') else 'identifier')
             for key in values if key.startswith('BK_GPU_')}
    return values, types
