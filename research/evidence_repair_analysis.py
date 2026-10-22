"""Paired, problem-level analysis for the registered evidence repair study."""
from collections import Counter,defaultdict
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
from replay import read,save
BATCH=ROOT/'实验/主动证据修复_2026-10-23_01'
FIELDS=('family','mode','scenario','policy','seed','budget')


def key(row):
    return tuple(row[k] for k in FIELDS)


def paired(left,right):
    a=np.asarray(left,dtype=np.int8); b=np.asarray(right,dtype=np.int8)
    assert a.shape==b.shape and len(a)>0
    delta=a-b; gains=int(np.sum(delta==1)); losses=int(np.sum(delta==-1)); m=gains+losses
    p=min(1.0,float(Fraction(2*sum(math.comb(m,k) for k in range(min(gains,losses)+1)),2**m))) if m else 1.0
    rng=np.random.default_rng(20261023)
    boots=delta[rng.integers(0,len(a),size=(10000,len(a)))].mean(axis=1)
    return {'n':len(a),'left_correct':int(a.sum()),'right_correct':int(b.sum()),
            'gains':gains,'losses':losses,'difference':float(delta.mean()),
            'paired_bootstrap95':np.quantile(boots,[.025,.975]).tolist(),'mcnemar_exact_p':p}


def main():
    cases=[read(p) for p in sorted((BATCH/'case-results').glob('*.json'))]
    assert len(cases)==988 and len({c['id'] for c in cases})==988
    indexes={c['id']:{key(r):r for r in c['rows']} for c in cases}
    summary={'schema':'active-evidence-results.v1','n':len(cases),'primary_metric':'final delivered contract correctness',
             'independence':'problem ID; seed repetitions are not independent samples',
             'source_lock_sha256':sha256((BATCH/'input-manifest.json').read_bytes()).hexdigest(),
             'new_model_calls':0,'new_cost_CNY':0,'splits':{}}
    for split in ('all','train','dev','test'):
        group=[c for c in cases if split=='all' or c['source_split']==split]
        grouped=defaultdict(list)
        for c in group:
            for row in c['rows']: grouped[key(row)].append(row)
        cells=[]
        for groupkey,rows in sorted(grouped.items()):
            assert len(rows)==len(group)
            cells.append({**dict(zip(FIELDS,groupkey)),'n':len(rows),
                          **{name:sum(r[name] for r in rows) for name in ('success','repair','regression','abstained','feasible_correct','optimal_correct')},
                          'net_gain':sum(r['repair']-r['regression'] for r in rows),
                          'mean_queries':sum(r['attempts'] for r in rows)/len(rows),
                          'mean_answers':sum(r['answers'] for r in rows)/len(rows),
                          'evidence_violation_deliveries':sum(r['delivered_evidence_mismatches']>0 for r in rows)})
        primary= ('C','feasibility','clean','risk',17,4)
        summary['splits'][split]={'n':len(group),'initial_correct':sum(c['initial']['success'] for c in group),
            'peer_correct':sum(c['peer']['success'] for c in group),'pair_oracle_correct':sum(c['initial']['success'] or c['peer']['success'] for c in group),
            'candidate_covered':sum(c['candidate_coverage'] for c in group),
            'both_initial_invalid':sum(c['initial_errors']['A'] is not None and c['initial_errors']['B'] is not None for c in group),
            'candidate_sizes':dict(Counter(c['candidate_count'] for c in group)), 'cells':cells,
            'failure_ids':[c['id'] for c in group if not indexes[c['id']][primary]['success']],
            'coverage_failure_ids':[c['id'] for c in group if not c['candidate_coverage']]}
    test=[c for c in cases if c['source_split']=='test']
    contrasts=[
      ('A',('A','feasibility','clean','gated',17,4),('A','feasibility','clean','local',17,4)),
      ('B',('B','feasibility','one_wrong','gated_e1',17,4),('B','feasibility','one_wrong','gated_e0',17,4)),
      ('C',('C','feasibility','clean','risk',17,4),('C','feasibility','clean','maxsplit',17,4))]
    comparisons=[]
    for name,left,right in contrasts:
        l=[indexes[c['id']][left] for c in test]; r=[indexes[c['id']][right] for c in test]
        result=paired([v['success'] for v in l],[v['success'] for v in r])
        result.update(name=name,left=dict(zip(FIELDS,left)),right=dict(zip(FIELDS,right)),
                      regression_difference=(sum(v['regression'] for v in l)-sum(v['regression'] for v in r))/len(test))
        comparisons.append(result)
    running=0.0
    for rank,result in enumerate(sorted(comparisons,key=lambda r:r['mcnemar_exact_p'])):
        running=max(running,min(1.0,(len(comparisons)-rank)*result['mcnemar_exact_p']))
        result['holm_p']=running
        result['advance_gate']=result['difference']>=.05 and running<.05 and result['regression_difference']<=.01
    summary['primary_contrasts']=comparisons
    # Separate exploratory comparison with no-query deployment baseline.
    proposed=[indexes[c['id']][('C','feasibility','clean','risk',17,4)]['success'] for c in test]
    summary['exploratory_vs_A']=paired(proposed,[c['initial']['success'] for c in test])
    summary['MDE_sensitivity']=[{'paired_discordance':q,'n':len(test),'approximate_pp':100*2.8*math.sqrt(q/len(test))} for q in (.1,.25,.5)]
    summary['runtime']={'case_seconds_sum':sum(c['total_seconds'] for c in cases),
                        'preparation_seconds_sum':sum(c['preparation_seconds'] for c in cases),
                        'execution':read(BATCH/'all-execution.json')}
    summary['scientific_decision']='advance' if any(c['advance_gate'] for c in comparisons) else 'do_not_promote_new_policy; investigate coverage and identifiability bottlenecks'
    save(BATCH/'results.json',summary)
    print(json.dumps({k:summary[k] for k in ('n','primary_contrasts','exploratory_vs_A','MDE_sensitivity','scientific_decision')},indent=2))


if __name__=='__main__': main()
