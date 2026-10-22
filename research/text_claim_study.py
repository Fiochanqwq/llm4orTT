"""Freeze a narrow text grammar, then inspect all historical problems without relabeling."""
from collections import Counter
from pathlib import Path
import json
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
from replay import read,save,sha,load_candidate
from text_claims import extract,contradicts

BATCH=ROOT/'实验/原文约束证据_2026-10-23_01'
COHORT=ROOT/'实验/任务板执行_2026-10-22_04/T8-screening-expanded/cases.private.json'

def register():
    if (BATCH/'prereg.json').exists():raise FileExistsError('Already registered')
    spec={'task':'T19','n':988,'MDE':None,'design':'Exploratory error mechanism; grammar developed from observed T17 training failures, then frozen before full scan',
      'arms':['official_reference','initial_A','initial_B'],
      'metric':'Count of models admitting an exact feasible point violating a source-grounded partial constraint; report grammar coverage separately',
      'rules':['explicit total item capacity','paired item production time and unique time budget','resource requirements and complete per-area rates'],
      'source':'Only original public text and supplied variable catalog enter extraction; labels and model scores are unavailable to extractor',
      'switching_rules':['Every flag must retain exact source spans, variable binding, rational row and feasible counterexample',
        'Any false text binding found in review requires a new version and batch, never silently editing results',
        'No frozen reference or primary correctness score is changed; suspected source conflicts are a separate research endpoint',
        'Use unhandled and ambiguous cases to select the next mechanism experiment, rather than claiming complete annotation repair'],
      'budget':{'new_model_calls':0,'new_cost_CNY':0},
      'sources':{p:sha(ROOT/p) for p in ['research/text_claims.py','research/text_claim_study.py','tests/test_text_claims.py']},
      'cohort_sha256':sha(COHORT)}
    save(BATCH/'prereg.json',spec)
    for p in spec['sources']:
        t=BATCH/'source-snapshot'/p;t.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,t)
    (BATCH/'execution.log').write_text('预估调用数：0；预估费用：0元；原文局部约束检查。\n',encoding='utf-8')
    return spec

def run():
    spec=read(BATCH/'prereg.json');assert all(sha(ROOT/p)==h for p,h in spec['sources'].items())
    rows=[]
    for c in read(COHORT):
        claims=extract(c['text'],c['variables'])
        models={'official_reference':c['reference'],**{a:load_candidate(ROOT/c['initial_source'],c,a).get('model') for a in ('A','B')}}
        rows.append({'id':c['id'],'split':c['source_split'],'text':c['text'],'variables':c['variables'],
                     'claims':[{**claim,'models':{a:contradicts(m,claim) for a,m in models.items()}} for claim in claims]})
    summaries=[]
    for split in ('all','train','dev','test'):
        group=[r for r in rows if split=='all' or r['split']==split]
        summaries.append({'split':split,'n':len(group),'covered_cases':sum(bool(r['claims']) for r in group),
          'claims':sum(len(r['claims']) for r in group),'rule_counts':dict(Counter(c['rule'] for r in group for c in r['claims'])),
          'contradicting_cases':{a:[r['id'] for r in group if any(c['models'][a]['witness'] is not None for c in r['claims'])] for a in models}})
    result={'schema':'text-claim-evidence.v1','n':len(rows),'rows':rows,'summaries':summaries,'primary_scores_modified':False,'new_model_calls':0,'new_cost_CNY':0}
    save(BATCH/'results.json',result)
    return {k:v for k,v in result.items() if k!='rows'}

if __name__=='__main__':print(json.dumps(register() if sys.argv[1]=='register' else run(),ensure_ascii=False,indent=2))
