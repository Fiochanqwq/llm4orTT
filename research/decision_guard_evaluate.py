"""Offline, exploratory evaluation of the frozen source-grounded guard."""
import hashlib
import json
from pathlib import Path
from decision_contract_study import OUT, cases, candidate, save, mcnemar
from decision_geometry import compare_models
from decision_semantic_guard import repair_model

def run():
    sources = [Path(__file__).with_name('decision_semantic_guard.py'),
               Path(__file__).with_name('decision_geometry.py')]
    freeze = {'timing': 'Before guard heldout evaluation; implementation agent used development text only. Original arm scores already exist.',
              'hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    save(OUT/'semantic-guard-source-freeze.json',freeze)
    results=[]
    for case in cases('heldout'):
        c=candidate(case,'A')
        row={'id':case['id'],'baselineValid':c['valid']}
        if c['valid']:
            patch=repair_model(case['text'],case['variables'],c['model'])
            before=compare_models(case['reference'],c['model'])
            after=compare_models(case['reference'],patch['model'])
            row.update({'baselineSuccess':before['feasible_sets_equal'] and before['optimal_faces_equal'],
                        'guardSuccess':after['feasible_sets_equal'] and after['optimal_faces_equal'],
                        'patch':patch,'comparison':after})
        else: row.update({'baselineSuccess':False,'guardSuccess':False})
        results.append(row)
    paired=mcnemar([r['baselineSuccess'] for r in results],[r['guardSuccess'] for r in results])
    summary={'scope':'Exploratory deterministic source-grounded guard; no added model calls; no global semantic guarantee',
             'n':len(results),'baselineSuccess':sum(r['baselineSuccess'] for r in results),
             'guardSuccess':sum(r['guardSuccess'] for r in results),'paired':paired,
             'extracted':sum(bool(r.get('patch',{}).get('before',{}).get('checks')) for r in results),
             'changed':sum(r.get('patch',{}).get('changed',False) for r in results),
             'flaggedWrong':sum(not r['baselineSuccess'] and r.get('patch',{}).get('before',{}).get('status')=='percentage_mismatch' for r in results),
             'flaggedCorrect':sum(r['baselineSuccess'] and r.get('patch',{}).get('before',{}).get('status')=='percentage_mismatch' for r in results)}
    save(OUT/'semantic-guard-scores.json',results); save(OUT/'semantic-guard-summary.json',summary)
    print(json.dumps(summary))

if __name__=='__main__': run()
