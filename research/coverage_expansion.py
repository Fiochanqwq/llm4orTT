"""Training-only diagnostic pilot: generate candidates beyond a frozen local bank."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
from replay import read,save,sha,load_candidate,exact_binomial_interval
from decision_geometry import compare_models
import evidence_repair as method
from evidence_repair_analysis import paired

OLD=ROOT/'实验/主动证据修复_2026-10-23_01'
BATCH=ROOT/'实验/候选扩展_2026-10-23_01'
COHORT=ROOT/'实验/任务板执行_2026-10-22_04/T8-screening-expanded/cases.private.json'
SYSTEM='''Translate the problem into a two-variable continuous nonnegative linear program.
Return only JSON with exactly these keys: {"sense":"max" or "min","objective":[c0,c1],"constraints":[{"a":[a0,a1],"op":"<=" or ">=" or "=","b":rhs}]}.
Use the supplied variable order. Every number must be a JSON number or rational string such as "1/3". Nonnegativity is implicit. Do not add integer restrictions or extra keys. Preserve every stated restriction and the objective meaning. Recheck direction, ratios, and bounds. A previous candidate may be wrong; correct it if the problem warrants it. Output the complete model, not a patch or explanation.'''


def evidence_for(row):
    transcript=next(t for t in row['transcripts'] if t['family']=='fixed' and t['mode']=='feasibility')
    return [{**row['prepared']['queries'][q],'answer':bool(a)} for q,a in zip(transcript['queries'][:4],transcript['labels'][:4])]


def passes_evidence(model,evidence):
    return model is not None and all(method.membership(model,e['kind'],e['point'])==e['answer'] for e in evidence)


def register():
    if (BATCH/'prereg.json').exists(): raise FileExistsError('This batch is already registered')
    cases={c['id']:c for c in read(COHORT)}
    rows=[read(p) for p in (OLD/'case-results').glob('*.json')]
    train=[r for r in rows if r['source_split']=='train']
    groups={'uncovered':[r for r in train if not r['candidate_coverage']],
            'correct_control':[r for r in train if r['initial']['success']]}
    chosen=[]
    for group,pool in groups.items():
        selected=sorted(pool,key=lambda r:sha256(('coverage-pilot-20261023:'+r['id']).encode()).hexdigest())[:40]
        assert len(selected)==40
        chosen.extend((group,row) for row in selected)
    queue=[]; selected=[]
    for group,row in chosen:
        case=cases[row['id']]
        assert case['source_split']=='train'
        initial=load_candidate(ROOT/case['initial_source'],case,'A').get('model')
        evidence=evidence_for(row)
        base=f"Problem: {case['text']}\nVariable order: {json.dumps(case['variables'],ensure_ascii=False)}\nPrevious candidate: {json.dumps(initial)}"
        for arm in ('reread','evidence_patch'):
            content=base
            if arm=='evidence_patch':
                content+='\nVerified feasibility checks (coordinates follow the variable order; answer=true means satisfies ALL problem constraints): '+json.dumps(evidence)+'\nUse these checks together with the problem text. They are partial checks, not a complete specification.'
            queue.append({'id':case['id']+'_'+arm,'maxTokens':1536,'json':True,
                          'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':content}]})
        selected.append({'id':case['id'],'stratum':group,'source_split':'train','initial_source':case['initial_source'],
                         'evidence':evidence,'initial_correct':row['initial']['success'],
                         'source_case_sha256':sha(OLD/'case-results'/(case['id']+'.json'))})
    # Deterministic request order balances arms over temporal service changes.
    queue.sort(key=lambda item:sha256(('request-order:'+item['id']).encode()).hexdigest())
    prior=ROOT/'实验/任务板执行_2026-10-22_04/T11'
    reports=read(prior/'budget.json')['prior_spend_reports']+[{'path':(prior/'budget-spend.json').relative_to(ROOT).as_posix(),'sha256':sha(prior/'budget-spend.json')}]
    brought=sum(read(ROOT/r['path']).get('current_run_accounted_CNY',read(ROOT/r['path'])['accounted_upper_CNY']) for r in reports)
    # UTF-8 bytes plus envelope allowance is the transport's conservative input bound.
    input_upper=sum(len(json.dumps(q['messages'],ensure_ascii=False,separators=(',',':')).encode())+256 for q in queue)
    output_upper=sum(q['maxTokens'] for q in queue)
    peak=(input_upper*2+output_upper*8)/1e6
    budget={'total_CNY':15,'stop_remaining_CNY':3,'max_model_calls':160,'automatic_retries':0,'prior_spend_reports':reports}
    prereg={'schema':'candidate-expansion.v1','task':'T17','n':80,'training_only':True,
      'sampling':'40 historically uncovered plus 40 initially correct, each hash-ranked; diagnostic outcome-stratified cohort, not population accuracy',
      'eligible_strata':{k:len(v) for k,v in groups.items()},'selection_seed':'coverage-pilot-20261023',
      'MDE':{'n_pairs':80,'alpha':.05,'power':.8,'discordance_assumption':.25,'approximate_absolute_difference':.1565,'role':'feasibility pilot, no independent confirmatory claim'},
      'arms':['reread','evidence_patch','evidence_patch+gate'],
      'calls_per_problem':2,'gate':'Third delivery arm uses the exact evidence_patch response; accept iff valid and every provided check passes; otherwise keep original A',
      'primary_metric':'final delivered feasible set and optimal face equivalent to the official reference, all 80 problems retained',
      'primary_contrasts':['evidence_patch+gate minus evidence_patch','evidence_patch minus reread'],
      'statistics':'problem-paired exact McNemar; Holm over two contrasts; paired bootstrap 10000 seed20261023; report each 40-case stratum separately',
      'oracle':'At most four candidate-only fixed-sequence feasibility questions, answered by official reference; reference coefficients never enter prompts',
      'failure_policy':'Transport, malformed, truncated response score failure; gate falls back to original A; never retry',
      'switching_rules':['Stop for budget floor or 3 transport failures; no automatic retries',
          'Retain a generator for a later independent study only if it fixes at least 8/40 uncovered problems and damages at most 2/40 correct controls',
          'If evidence does not beat reread by at least 4/80 net deliveries, prefer reread as the simpler candidate generator',
          'Do not change prompts, selected cohort, endpoints, or scoring after requests begin'],
      'budget':budget,'estimate':{'calls':160,'input_token_upper':input_upper,'output_token_upper':output_upper,
          'brought_forward_CNY':brought,'costs':{'peak':{'total_CNY':peak},'off_peak':{'total_CNY':peak/2}}},
      'price_source':'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/','price_checked_date':'2026-10-23'}
    assert brought+peak<=12
    save(BATCH/'selected.json',selected);save(BATCH/'queue.json',queue);save(BATCH/'prereg.json',prereg)
    save(BATCH/'budget.json',{'schema':'task-board-budget.v2',**budget,'model':'deepseek-flash',
          'prices':{'peak':{'hit':.04,'miss':2,'output':8},'off_peak':{'hit':.02,'miss':1,'output':4}},
          'queue_sha256':sha(BATCH/'queue.json'),'prereg_sha256':sha(BATCH/'prereg.json')})
    sources=['research/coverage_expansion.py','research/evidence_repair.py','research/evidence_repair_analysis.py',
             'research/decision_geometry.py','research/replay.py','scripts/decision-contract-api.mjs']
    lock={s:sha(ROOT/s) for s in sources}
    save(BATCH/'input-manifest.json',{'sources':lock,'cohort_sha256':sha(COHORT),'selected_sha256':sha(BATCH/'selected.json'),
                                     'old_registration_sha256':sha(OLD/'input-manifest.json')})
    for name in sources:
        target=BATCH/'source-snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    (BATCH/'execution.log').write_text(f'预估调用数：160；预估费用：峰值上界 {peak:.8f} 元，历史累计 {brought:.8f} 元，总额上限15元，保留3元。\n',encoding='utf-8')
    return prereg['estimate']


def analyze():
    cases={c['id']:c for c in read(COHORT)}; rows=[]
    for selection in read(BATCH/'selected.json'):
        case=cases[selection['id']]; initial=load_candidate(ROOT/case['initial_source'],case,'A').get('model')
        models={arm:load_candidate(BATCH,case,arm).get('model') for arm in ('reread','evidence_patch')}
        accepted=passes_evidence(models['evidence_patch'],selection['evidence'])
        models['evidence_patch+gate']=models['evidence_patch'] if accepted else initial
        scores={arm:bool(m is not None and compare_models(case['reference'],m)['equivalent']) for arm,m in models.items()}
        rows.append({**selection,'gate_accepted':accepted,'success':scores,
                     'valid':{a:m is not None for a,m in models.items()},
                     'evidence_satisfied':{a:passes_evidence(m,selection['evidence']) for a,m in models.items()},
                     'models':models})
    result={'schema':'candidate-expansion-results.v1','n':len(rows),'rows':rows,'strata':{},'comparisons':[],
            'budget':read(BATCH/'budget-spend.json')}
    for stratum in ('all','uncovered','correct_control'):
        group=[r for r in rows if stratum=='all' or r['stratum']==stratum]
        result['strata'][stratum]={'n':len(group),'initial_correct':sum(r['initial_correct'] for r in group),
            'arms':{a:{'correct':sum(r['success'][a] for r in group),
                 'repairs':sum(r['success'][a] and not r['initial_correct'] for r in group),
                 'regressions':sum(not r['success'][a] and r['initial_correct'] for r in group),
                 'invalid':sum(not r['valid'][a] for r in group)} for a in models}}
    for a,b in (('evidence_patch+gate','evidence_patch'),('evidence_patch','reread')):
        result['comparisons'].append({'left':a,'right':b,**paired([r['success'][a] for r in rows],[r['success'][b] for r in rows])})
    running=0
    for i,c in enumerate(sorted(result['comparisons'],key=lambda c:c['mcnemar_exact_p'])):
        running=max(running,min(1,(2-i)*c['mcnemar_exact_p']));c['holm_p']=running
    result['retained_generators']=[a for a in models if result['strata']['uncovered']['arms'][a]['repairs']>=8 and result['strata']['correct_control']['arms'][a]['regressions']<=2]
    result['evidence_increment']=result['strata']['all']['arms']['evidence_patch']['correct']-result['strata']['all']['arms']['reread']['correct']
    result['gate_rejections']=sum(not r['gate_accepted'] for r in rows)
    save(BATCH/'results.json',result)
    return {k:v for k,v in result.items() if k!='rows'}


if __name__=='__main__':
    print(json.dumps(register() if sys.argv[1]=='register' else analyze(),ensure_ascii=False,indent=2))
