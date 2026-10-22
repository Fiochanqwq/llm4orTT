"""Exploratory follow-up registered after observing the new training pilot."""
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
from replay import read,save,sha,load_candidate
from decision_geometry import compare_models
from evidence_repair_analysis import paired
import evidence_repair as method
import fresh_evidence as fresh
from coverage_expansion import passes_evidence

BATCH=ROOT/'实验/更新后分歧检查_2026-10-23_01'
OLD=ROOT/'实验/主动证据修复_2026-10-23_01'
NEW=ROOT/'实验/候选扩展_2026-10-23_01'
COHORT=ROOT/'实验/任务板执行_2026-10-22_04/T8-screening-expanded/cases.private.json'

def register():
    if (BATCH/'prereg.json').exists():raise FileExistsError('Already registered')
    spec={'task':'T18','schema':'fresh-evidence.v1','n':{'historical_pairs':988,'new_training_pilot':80},
      'MDE':None,'purpose':'Exploratory mechanism test after observing T17 training outcomes; not a new independent validation',
      'primary_metric':'correctness of delivered feasible set and optimal face, exact reference comparison',
      'arms':['raw_proposal','stale_evidence_gate','fresh_separator_gate'],
      'policies':'Generate at most one new separating point after seeing the candidate. Accept only when its truthful label contradicts the original and agrees with the proposal. Missing labels retain the original.',
      'matched_allowance':'T17 stale gate uses original up-to-4 checks; stale5 uses up to one additional fixed pre-generation check; fresh uses up to one post-generation check. Report actual query counts separately; not equal realized query counts.',
      'oracles':['feasibility primary','joint feasibility/optimality secondary, stronger access'],
      'invalid':'Invalid proposal keeps original; invalid original may accept a valid proposal without confirmation and remains scored',
      'budget':{'new_model_calls':0,'new_cost_CNY':0},
      'switching_rules':['Any regression under truthful oracle rejects the implementation theorem claim',
        'Generator stays rejected if the T17 preregistered repair threshold failed; gate does not reverse generator decision',
        'Freeze outputs and report exploratory comparisons without confirmatory significance claims'],
      'sources':{p:sha(ROOT/p) for p in ['research/fresh_evidence.py','research/fresh_evidence_study.py','tests/test_fresh_evidence.py','research/evidence_repair.py']},
      'input_hashes':{'cohort':sha(COHORT),'new_results':sha(NEW/'results.json'),'old_results':sha(OLD/'results.json')}}
    save(BATCH/'prereg.json',spec)
    for p in spec['sources']:
        target=BATCH/'source-snapshot'/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,target)
    (BATCH/'execution.log').write_text('预估调用数：0；预估费用：0元；精确模拟确认，探索性后续。\n',encoding='utf-8')
    return spec

def execute():
    spec=read(BATCH/'prereg.json')
    assert all(sha(ROOT/p)==v for p,v in spec['sources'].items())
    cases=read(COHORT);new={r['id']:r for r in read(NEW/'results.json')['rows']};rows=[]
    for c in cases:
        a=load_candidate(ROOT/c['initial_source'],c,'A').get('model')
        b=load_candidate(ROOT/c['initial_source'],c,'B').get('model')
        def oracle(q):return method.membership(c['reference'],q['kind'],q['point'])
        def correct(m):return bool(m is not None and compare_models(c['reference'],m)['equivalent'])
        initial=correct(a)
        for mode in ('feasibility','joint'):
            out=fresh.deliver(a,b,oracle,mode)
            rows.append({'id':c['id'],'cohort':'historical','split':c['source_split'],'arm':'fresh_B','mode':mode,
                'initial':initial,'raw':correct(b),'success':correct(out['model']),'queries':out['queries'],'reason':out['reason']})
        if c['id'] in new:
            n=new[c['id']];p=n['models']['evidence_patch']
            historical=read(OLD/'case-results'/(c['id']+'.json'))
            t=next(t for t in historical['transcripts'] if t['family']=='fixed' and t['mode']=='feasibility')
            e5=[{**historical['prepared']['queries'][q],'answer':v} for q,v in zip(t['queries'][:5],t['labels'][:5])]
            accepted5=passes_evidence(p,e5)
            for mode in ('feasibility','joint'):
                out=fresh.deliver(a,p,oracle,mode)
                rows.append({'id':c['id'],'cohort':'new_training','split':n['stratum'],'arm':'fresh_patch','mode':mode,
                    'initial':initial,'raw':correct(p),'success':correct(out['model']),'queries':out['queries'],'reason':out['reason'],
                    'old_gate':n['success']['evidence_patch+gate'],'stale5_gate':correct(p if accepted5 else a),
                    'stale_queries':len(n['evidence']),'stale5_queries':len(e5)})
    result={'schema':'fresh-evidence-results.v1','rows':rows,'summaries':[],'new_model_calls':0,'new_cost_CNY':0}
    for cohort in ('historical','new_training'):
        for split in ('all',)+tuple(sorted({r['split'] for r in rows if r['cohort']==cohort})):
            for mode in ('feasibility','joint'):
                group=[r for r in rows if r['cohort']==cohort and r['mode']==mode and (split=='all' or r['split']==split)]
                cell={'cohort':cohort,'split':split,'mode':mode,'n':len(group),'initial_correct':sum(r['initial'] for r in group),
                      'raw_correct':sum(r['raw'] for r in group),'fresh_correct':sum(r['success'] for r in group),
                      'repairs':sum(r['success'] and not r['initial'] for r in group),
                      'regressions':sum(not r['success'] and r['initial'] for r in group),'fresh_queries':sum(len(r['queries']) for r in group)}
                if cohort=='new_training':cell.update(old_gate_correct=sum(r['old_gate'] for r in group),
                    stale5_correct=sum(r['stale5_gate'] for r in group),stale_queries=sum(r['stale_queries'] for r in group),
                    stale5_queries=sum(r['stale5_queries'] for r in group),
                    exploratory_vs_old=paired([r['success'] for r in group],[r['old_gate'] for r in group]))
                result['summaries'].append(cell)
    result['truthful_oracle_regressions']=sum(not r['success'] and r['initial'] for r in rows)
    result['implementation_passed']=result['truthful_oracle_regressions']==0
    save(BATCH/'results.json',result)
    with (BATCH/'execution.log').open('a',encoding='utf-8') as f:f.write(f'Completed {len(cases)} historical pairs and {len(new)} new training outputs.\n')
    return {k:v for k,v in result.items() if k!='rows'}

if __name__=='__main__':print(json.dumps(register() if sys.argv[1]=='register' else execute(),ensure_ascii=False,indent=2))
