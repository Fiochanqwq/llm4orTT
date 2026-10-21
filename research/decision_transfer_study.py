"""Small adaptive transfer follow-up, isolated from the original primary study."""
import argparse
import hashlib
import json
import random
import re
from pathlib import Path
from decision_contract_study import ROOT,OUT,read,save,canonical_record,public_prompt,request,mcnemar,digest
from decision_geometry import analyze_model,compare_models

def prepare():
    admission=read(OUT/'admission.json'); permitted=set(admission['unselectedEligible'])
    pool=[]
    for line in (ROOT/'datasets/llm-grounding-v1/nl4opt-test.jsonl').read_text('utf-8').splitlines():
        for identifier,record in json.loads(line).items():
            if identifier not in permitted or not re.search(r'\bat (?:least|most)\s+\d+(?:\.\d+)?\s*%',record['document'],re.I):continue
            pool.append({'id':identifier,'text':record['document'],'variables':record['vars'],'reference':canonical_record(identifier,record)})
    pool.sort(key=lambda c:c['id']);random.Random(202610216).shuffle(pool)
    if len(pool)<11:raise ValueError('Not enough untouched public percentage problems: '+str(len(pool)))
    chosen=pool[:11]
    save(OUT/'transfer-cases.private.json',chosen)
    save(OUT/'transfer-protocol.json',{'schema':'adaptive-transfer.v1','n':11,'poolN':len(pool),
        'selection':'Unselected eligible public problems containing at least/at most numeric percent; sorted IDs then seed202610216 shuffle; no selection on model outputs or guard extraction success',
        'cohort':[c['id'] for c in chosen],'development':'v2 uses old development and already observed original heldout errors; original60 cohort no longer independent for v2',
        'freeze':'Module must be frozen before new responses are scored; implementer cannot access these11 cases',
        'primary':'all11 initial A vs same-output deterministic v2; reference feasible-region AND optimal-face equality',
        'tests':'exact paired McNemar and10000 paired bootstrap; exploratory, small enriched cohort, no multiplicity-adjusted superiority claim',
        'budget':'11 new baseline calls, zero calls for guards; total round ceiling300',
        'references':'Offline only; same official annotation caveat as original study',
        'sourceSha256':digest(ROOT/'datasets/llm-grounding-v1/nl4opt-test.jsonl')})
    queue=[]
    for c in chosen:
        content=public_prompt(c);content['instruction']='Construct the complete LP directly from the original description.'
        queue.append(request('transfer_'+c['id']+'_A',content))
    save(OUT/'transfer-initial-queue.json',queue)
    print(json.dumps({'poolN':len(pool),'selected':len(chosen)}))

def evaluate():
    from decision_semantic_guard_v2 import repair_model
    freeze=read(OUT/'semantic-guard-v2-freeze.json')
    assert freeze['sha256']==digest(ROOT/'research/decision_semantic_guard_v2.py')
    rows=[]
    for case in read(OUT/'transfer-cases.private.json'):
        row={'id':case['id'],'baselineSuccess':False,'guardSuccess':False,'valid':False}
        try:
            result=read(OUT/'network'/('transfer_'+case['id']+'_A.result.json'))
            if result['status']!='complete':raise ValueError('request not complete')
            model=json.loads(result['text']);analyze_model(model)
            patch=repair_model(case['text'],case['variables'],model)
            before=compare_models(case['reference'],model);after=compare_models(case['reference'],patch['model'])
            row.update({'valid':True,'model':model,'patch':patch,'before':before,'after':after,
                'baselineSuccess':before['feasible_sets_equal'] and before['optimal_faces_equal'],
                'guardSuccess':after['feasible_sets_equal'] and after['optimal_faces_equal']})
        except (ValueError,KeyError,TypeError) as error:row['error']=str(error)
        rows.append(row)
    summary={'scope':'Adaptive, percentage-enriched transfer cohort, not original confirmatory endpoint',
        'n':len(rows),'valid':sum(r['valid'] for r in rows),'baselineSuccess':sum(r['baselineSuccess'] for r in rows),
        'guardSuccess':sum(r['guardSuccess'] for r in rows),
        'extracted':sum(bool(r.get('patch',{}).get('before',{}).get('checks')) for r in rows),
        'changed':sum(r.get('patch',{}).get('changed',False) for r in rows),
        'paired':mcnemar([r['baselineSuccess'] for r in rows],[r['guardSuccess'] for r in rows])}
    save(OUT/'transfer-scores.json',rows);save(OUT/'transfer-summary.json',summary);print(json.dumps(summary))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','evaluate']);args=parser.parse_args()
    {'prepare':prepare,'evaluate':evaluate}[args.stage]()
