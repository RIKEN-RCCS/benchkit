import copy
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils.comparison_evidence import build_condition_evidence


def record(exp='CASE0'):
    return {'data': {'code': 'demo', 'system': 'ExampleSystem', 'Exp': exp,
        'node_count': 1, 'numproc_node': 1, 'nthreads': 32,
        'FOM_version': 'Solver', 'FOM_unit': 's',
        'source_info': {'commit_hash': 'a' * 40},
        'input_info': {'inputs': [{'kind': 'runtime-parameters',
            'dataset_id': 'command-parameters', 'arguments': ['32', '6']} ]}}}


def test_old_and_new_names_are_candidates_only_with_recorded_input_evidence():
    a, b = record('old.ramble.experiment'), record()
    evidence = build_condition_evidence([a, b])
    assert evidence['relationships'][0]['status'] == 'related input candidate'
    assert a['data']['Exp'] == 'old.ramble.experiment'
    b['data'].pop('input_info')
    assert build_condition_evidence([a,b])['relationships'][0]['status'] == 'insufficient evidence'
    b = record('old.ramble.experiment')
    b['data']['input_info']['inputs'][0]['arguments'] = ['64', '6']
    assert build_condition_evidence([a,b])['relationships'][0]['status'] == 'recorded difference'


def test_conditions_cover_intermediate_results_and_unknowns():
    a,b,c = record(),record(),record()
    b['data']['nthreads'] = 72
    b['data']['source_info']['commit_hash'] = 'b' * 40
    c['data'].pop('FOM_unit')
    conditions = {row['label']:row['status'] for row in build_condition_evidence([a,b,c])['conditions']}
    assert conditions['Threads per rank'] == 'recorded difference'
    assert conditions['Source commit'] == 'recorded difference'
    assert conditions['FOM unit'] == 'insufficient evidence'
    assert conditions['Build record'] == 'insufficient evidence'


def test_partial_or_unexpanded_inputs_do_not_create_candidates():
    for item in [{'kind':'runtime-parameters','arguments':['$SIZE']},
                 {'kind':'runtime-parameters','arguments':['32'],'collection_status':'unavailable'},
                 {'kind':'runtime-parameters','arguments':[]}, {'sha256':'a'*64}]:
        a,b=record(),record()
        a['data']['input_info']['inputs'].append(item)
        b=copy.deepcopy(a)
        assert build_condition_evidence([a,b])['relationships'][0]['status'] == 'insufficient evidence'


def test_scope_and_generic_fom_do_not_establish_equivalence():
    a,b=record(),record()
    b['data']['system']='OtherSystem'
    b['data']['FOM_version']='Figure of Merit (FOM)'
    evidence=build_condition_evidence([a,b])
    assert evidence['relationships'][0]['status']=='different code/system'
    assert next(c for c in evidence['conditions'] if c['label']=='FOM definition')['status']=='insufficient evidence'


def test_discovery_distinguishes_missing_different_and_matching_without_renaming():
    from utils.comparison_evidence import find_related_candidates
    a=record();a['filename']='current.json'
    same=record('old.ramble');same['filename']='old.json'
    missing=record('unknown');missing['filename']='missing.json';missing['data'].pop('input_info')
    different=record('different');different['filename']='different.json'
    different['data']['input_info']['inputs'][0]['arguments']=['99']
    result=find_related_candidates([a],[a,same,missing,different])
    assert [r['filename'] for r in result['candidates']]==['old.json']
    assert result['insufficient_pairs']==1
    assert result['different_pairs']==1
    assert same['data']['Exp']=='old.ramble'


def test_known_differences_remain_visible_when_another_result_is_unobserved():
    a,b,c=record(),record(),record()
    b['data']['nthreads']=72
    c['data'].pop('nthreads')
    condition=next(r for r in build_condition_evidence([a,b,c])['conditions'] if r['label']=='Threads per rank')
    assert condition['status']=='recorded difference (incomplete evidence)'
