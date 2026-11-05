"""Annotation payloads can exceed exec argument limits without changing science."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_annotation_stream_handles_large_ensemble_and_preserves_notes(tmp_path):
    result = tmp_path/'result.json'
    result.write_text(json.dumps({'fom_breakdown':{'sections':[
        {'name':'pme_real_wait','time':8}, {'name':'pme_real_inter','time':1},
        {'name':'pme_real_intra','time':1}]}}))
    for label, size in [('small',0),('large',300000)]:
        payload = tmp_path/(label+'.json')
        payload.write_text(json.dumps({'sections':[{'name':'pairlist','candidate_estimates':[]}],
                                       'retained_evidence':'x'*size}))
        script = '''
set -euo pipefail
source programs/genesis/estimate.sh
est_future_fom_breakdown=$(cat "$2")
est_assumptions_json='{"existing_note":true}'
bk_estimation_apply_annotation genesis_estimation_assumptions "$1"
printf '%s\\n' "$est_assumptions_json"
'''
        env = {k:v for k,v in os.environ.items() if not k.startswith('BK_')}
        output = subprocess.check_output(['bash','-c',script,'annotation-test',str(result),str(payload)],
                                         cwd=ROOT,env=env,text=True)
        notes = json.loads(output)
        if label == 'small':
            expected = notes
        else:
            assert notes == expected
    assert expected['existing_note'] is True
    assert expected['genesis']['pme_real_partition']['fractions']=={
        'pme_real_wait':.8,'pme_real_inter':.1,'pme_real_intra':.1}
    assert expected['genesis']['gpu_specifications']==[]
