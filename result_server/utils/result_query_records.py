"""Small, versioned report facts; never a second copy of the Result document."""

from utils.benchpark import result_pipeline_backend
from utils.public_reuse import has_public_input_info, has_public_source_info
from utils.result_file import _extract_confidential_tags
from utils.result_records import summarize_result_quality
from utils.trigger_display import extract_execution_trigger


def _fields(value, names):
    if not isinstance(value, dict):
        return value
    return {name: value[name] for name in names if name in value}


def report_facts(data):
    """Preserve missing/invalid values and existing calculation semantics."""
    facts = {key: data[key] for key in (
        'code', 'system', 'Exp', 'exp', 'FOM', 'FOM_unit', 'FOM_version',
        'node_count', 'numproc_node', 'nthreads', 'execution_mode', 'pipeline_id',
    ) if key in data}
    facts['execution_backend'] = result_pipeline_backend(data)
    facts['execution_trigger'] = extract_execution_trigger(data)
    facts['pipeline_timing'] = _fields(data.get('pipeline_timing'), (
        'build_time', 'queue_time', 'run_time', 'scheduler_queue_time',
        'queue_time_source', 'scheduler_queue_time_source', 'profiled_run_included', 'profiled_job'))
    cache = data.get('build_cache')
    facts['build_cache'] = (_fields(cache, ('status', 'stored')) or {'recorded': True}) if isinstance(cache, dict) and cache else cache
    profile = data.get('profile_data')
    facts['profile_data'] = {'recorded': True} if isinstance(profile, dict) and profile else None
    snapshot = data.get('environment_snapshot')
    if isinstance(snapshot, dict):
        facts['environment_snapshot'] = _fields(snapshot, ('hash',))
        facts['environment_snapshot']['summary'] = _fields(snapshot.get('summary'), (
            'system', 'allocation_project_id', 'scheduler', 'runner'))
    for key in ('current_system', 'future_system'):
        value = data.get(key)
        facts[key] = _fields(value, ('system',))
        if isinstance(value, dict) and 'benchmark' in value:
            facts[key]['benchmark'] = _fields(value['benchmark'], ('system',))
    meta = data.get('estimate_metadata')
    facts['estimate_metadata'] = _fields(meta, ('estimation_result_timestamp',))
    if isinstance(meta, dict):
        for key in ('source_result', 'future_source_result'):
            if key in meta:
                facts['estimate_metadata'][key] = _fields(meta[key], ('system',))
    facts['estimation_timing'] = _fields(data.get('estimation_timing'), (
        'elapsed_time', 'elapsed_seconds', 'duration_seconds', 'duration'))
    facts['applicability'] = _fields(data.get('applicability'), ('status',))
    quality = summarize_result_quality(data)
    public_source = has_public_source_info(data.get('source_info'))
    return facts, {
        'level': quality['level'],
        'source_complete': quality['stats']['source_info_complete'],
        'input_label': quality['stats']['input_info_label'],
        'public': not _extract_confidential_tags(data),
        'public_source': public_source,
        'public_input': has_public_input_info(data.get('input_info'), public_source, result=data),
    }
