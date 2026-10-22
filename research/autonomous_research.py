"""Persistent research checkpoints consumed by the scheduled research worker.

This records evidence and the next scientific experiment. The scheduled worker
performs reasoning and implementation; this CLI never repeats paid requests.
"""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'research/autonomous_state.json'
JOURNAL=ROOT/'research/autonomous_cycles.jsonl'

def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()

def discover():
    batches=[]
    for p in (ROOT/'实验').glob('*/prereg.json'):
        spec=read(p);task=spec.get('task','')
        result=p.parent/'results.json'
        if (isinstance(task,str) and task.startswith('T') and task[1:].isdigit() and int(task[1:])>=12 or spec.get('schema')=='active-evidence-repair.v1') and result.exists():
            batches.append({'task':task or 'T12-T16','path':p.parent.relative_to(ROOT).as_posix(),
                            'prereg_sha256':digest(p),'results_sha256':digest(result)})
    return sorted(batches,key=lambda x:x['path'])

def checkpoint():
    batches=discover();old=read(STATE) if STATE.exists() else {}
    reports=[(p,read(p)) for p in (ROOT/'实验').glob('**/budget-spend.json')]
    reports=[(p,b) for p,b in reports if b.get('total_budget_CNY')==15 and isinstance(b.get('accounted_upper_CNY'),(int,float))]
    budget_path,budget=max(reports,key=lambda item:item[1]['accounted_upper_CNY'])
    if old.get('completed_batches')==batches and old.get('budget_snapshot',{}).get('accounted_upper_CNY')==budget['accounted_upper_CNY']:
        return old
    state={**old,'schema':'autonomous-research.v1','status':'active','automation_id':'automation-2',
      'updated_utc':datetime.now(timezone.utc).isoformat(),'completed_batches':batches,
      'loop':['inspect unfavorable results','state a testable mechanism','register a separate batch','implement and execute','compare repairs and regressions','save evidence and queue next experiment'],
      'budget_snapshot':{'source':budget_path.relative_to(ROOT).as_posix(),'accounted_upper_CNY':budget['accounted_upper_CNY'],
                         'total_CNY':15,'reserved_floor_CNY':3,'automatic_retries':0},
      'continuation':'Reports are checkpoints, not a stopping rule. New evidence changes priorities; an unchanged result is not a reason to rerun the same experiment.'}
    if not old:
        state['next_experiments']=[
          {'task':'T21','priority':1,'hypothesis':'Text-grounded partial constraints can veto poisoned reference feedback before it harms an initially text-consistent model.',
           'trigger':'T19 found exact conflicts in four public references; T17 evidence harmed two correct answers.',
           'experiment':'Freeze a reference-independent source-claim extraction extension on training data. Compare reference-only feedback, source-veto feedback and no-update on the same proposed models and question budget. Keep official correctness as the original endpoint, and report text-claim violations as a separate endpoint with exact spans and witnesses.',
           'first_action':'Read all T19 covered claims including the unflagged time-capacity example; distinguish overly permissive from overly restrictive references. Register T21 before extending the grammar.',
           'max_new_model_calls':0,'status':'queued'},
          {'task':'T22','priority':2,'hypothesis':'Explicitly distinguishing share-of-invested-total from share-of-available-budget explains recurring investment failures and yields informative clarification questions.',
           'experiment':'Form both mathematically valid denominator interpretations from original text, find separating plans with exact arithmetic, and test query selection against a direct reread baseline. Keep ambiguity labels separate from original gold.',
           'max_new_model_calls':0,'status':'queued'},
          {'task':'T23','priority':3,'hypothesis':'A source-anchored ratio compiler generates useful repairs beyond copying A/B constraint rows.',
           'experiment':'Generate ratio and direction alternatives from quoted sentences and variable bindings, add them to the fixed local candidate bank, and compare matched-budget fresh checks and max-split checks. Develop on train, freeze before dev analysis, report historical test reuse explicitly.',
           'max_new_model_calls':0,'status':'queued'}]
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with JOURNAL.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'utc':state['updated_utc'],'event':'checkpoint','batches':batches,'next':state.get('next_experiments',[])},ensure_ascii=False)+'\n')
    return state

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='checkpoint':value=checkpoint()
    else:value=read(STATE)
    print(json.dumps(value,ensure_ascii=False,indent=2))
