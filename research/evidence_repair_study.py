"""Registered new experiments A/B/C on historical candidates, with no transport."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
import evidence_repair as method
from decision_geometry import compare_models
from replay import read,save,load_candidate

BATCH=ROOT/'实验/主动证据修复_2026-10-23_01'
COHORT=ROOT/'实验/任务板执行_2026-10-22_04/T8-screening-expanded/cases.private.json'
BUDGETS=(0,1,2,4,8)
SEEDS=(17,29,43)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    return {name:digest(ROOT/name) for name in ('research/evidence_repair.py','research/evidence_repair_study.py',
        'tests/test_evidence_repair.py','research/decision_geometry.py','research/replay.py')}


def register():
    if (BATCH/'input-manifest.json').exists():
        raise FileExistsError('Registration already exists')
    cases=read(COHORT)
    assert len(cases)==988 and len({c['id'] for c in cases})==988
    counts=dict(Counter(c['source_split'] for c in cases))
    assert counts=={'test':258,'train':645,'dev':85}, counts
    files={COHORT.relative_to(ROOT).as_posix():digest(COHORT)}
    missing=[]
    for c in cases:
        for arm in ('A','B'):
            file=ROOT/c['initial_source']/'network'/f'{c["id"]}_{arm}.result.json'
            if file.is_file():
                files[file.relative_to(ROOT).as_posix()]=digest(file)
            else:
                missing.append(file.relative_to(ROOT).as_posix())
    pilot=sorted((c for c in cases if c['source_split']=='dev'),key=lambda c:sha256(('pilot:'+c['id']).encode()).hexdigest())[:24]
    result={'schema':'evidence-input-lock.v1','n':len(cases),'split_counts':counts,
            'files':files,'missing_initial_files':missing,'source_hashes':source_hashes(),
            'prereg_sha256':digest(BATCH/'prereg.json'),'pilot_ids':[c['id'] for c in pilot]}
    save(BATCH/'input-manifest.json',result)
    for name in result['source_hashes']:
        target=BATCH/'source-snapshot'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
    return {'n':len(cases),'files':len(files),'pilot_n':len(pilot),'source_locked':True}


def run_case(case):
    start=time.monotonic()
    loaded={a:load_candidate(ROOT/case['initial_source'],case,a) for a in ('A','B')}
    initial=loaded['A'].get('model'); peer=loaded['B'].get('model')
    prepared=method.prepare(initial,peer)
    preparation_seconds=time.monotonic()-start
    scores=[]
    for candidate in prepared['bank']:
        comparison=compare_models(case['reference'],candidate['model'])
        assert comparison['equivalent']==(method.fingerprint(case['reference'])==method.fingerprint(candidate['model']))
        scores.append({name:comparison[key] for name,key in (
            ('success','equivalent'),('feasible_correct','feasible_sets_equal'),('optimal_correct','optimal_faces_equal'))})
    invalid={'success':False,'feasible_correct':False,'optimal_correct':False}
    def score(index):
        return invalid if index is None else scores[index]
    initial_score=score(prepared['initial_index'])
    def oracle(question):
        return method.membership(case['reference'],question['kind'],question['point'])
    rows,transcripts=[],[]
    def record(family,mode,scenario,policy,seed,budget,selected,abstained,attempts,evidence,remaining,loss=None):
        value=score(selected)
        rows.append({'family':family,'mode':mode,'scenario':scenario,'policy':policy,'seed':seed,'budget':budget,
                     'selected':None if selected is None else int(selected),'abstained':bool(abstained),
                     'attempts':attempts,'answers':sum(v is not None for _,v in evidence),'remaining':remaining,
                     'panel_loss':loss,**value,'repair':not initial_score['success'] and value['success'],
                     'regression':initial_score['success'] and not value['success'],
                     'delivered_evidence_mismatches':sum(v is not None and (selected is None or bool(prepared['predictions'][selected,q])!=v) for q,v in evidence)})
    for mode in ('feasibility','joint'):
        sequence=method.fixed_sequence(prepared,mode)
        labels=[oracle(prepared['queries'][q]) for q in sequence]
        transcripts.append({'family':'fixed','mode':mode,'queries':sequence,'labels':labels})
        for b in BUDGETS:
            evidence=list(zip(sequence[:b],labels[:b]))
            remaining=method.survivors(prepared,evidence)
            for selector in ('local','minimax','gated'):
                selected,abstained,loss=(prepared['initial_index'],True,None) if b==0 else method.choose(prepared,remaining,selector)
                record('A',mode,'clean',selector,17,b,selected,abstained,len(evidence),evidence,len(remaining),loss)
        for scenario in ('clean','missing_half','one_wrong'):
            for seed in (SEEDS if scenario=='missing_half' else (17,)):
                altered=method.evidence_variant(sequence,labels,scenario,case['id'],seed)
                for b in BUDGETS:
                    evidence=altered[:b]
                    for policy,selector,tolerance in (('local_e0','local',0),('gated_e0','gated',0),('gated_e1','gated',1)):
                        remaining=method.survivors(prepared,evidence,tolerance)
                        selected,abstained,loss=(prepared['initial_index'],True,None) if b==0 else method.choose(prepared,remaining,selector)
                        record('B',mode,scenario,policy,seed,b,selected,abstained,len(evidence),evidence,len(remaining),loss)
        for policy in ('random','maxsplit','risk'):
            for seed in (SEEDS if policy=='random' else (17,)):
                states=method.adaptive(prepared,oracle,mode,policy,seed)
                transcripts.append({'family':'C','mode':mode,'policy':policy,'seed':seed,
                                    'evidence':states[-1]['evidence']})
                for state in states:
                    if state['budget'] in BUDGETS:
                        record('C',mode,'clean',policy,seed,state['budget'],state['selected'],state['abstained'],
                               state['attempts'],state['evidence'],state['remaining'],state['loss'])
    # Pure no-evidence baselines are scored once per original problem.
    return {'id':case['id'],'source_split':case['source_split'],'initial_source':case['initial_source'],
            'initial_errors':{a:loaded[a].get('error') for a in ('A','B')},
            'initial':initial_score,'peer':score(prepared['peer_index']),
            'candidate_coverage':any(s['success'] for s in scores),'candidate_count':len(scores),
            'queries_by_kind':dict(Counter(q['kind'] for q in prepared['queries'])),
            'prepared':method.serializable(prepared),'candidate_scores':scores,
            'transcripts':transcripts,'rows':rows,'preparation_seconds':preparation_seconds,
            'total_seconds':time.monotonic()-start}


def execute(phase,workers):
    lock=read(BATCH/'input-manifest.json')
    if lock['source_hashes']!=source_hashes() or lock['prereg_sha256']!=digest(BATCH/'prereg.json'):
        raise ValueError('Source or registration changed after lock; preserve batch and register an amendment/new batch')
    cases=read(COHORT)
    if phase=='pilot':
        cases=[c for c in cases if c['id'] in lock['pilot_ids']]
    destination=BATCH/'case-results'; destination.mkdir(exist_ok=True)
    pending=[c for c in cases if not (destination/(c['id']+'.json')).is_file()]
    for case in pending:
        if not case['id'].lstrip('-').isdigit():
            raise ValueError('Unsafe case ID')
    errors=[]; start=time.monotonic()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(run_case,c):c['id'] for c in pending}
        for i,future in enumerate(as_completed(futures),1):
            identifier=futures[future]
            try:
                result=future.result()
                save(destination/(identifier+'.json'),result)
            except Exception:
                error={'id':identifier,'traceback':traceback.format_exc()}
                errors.append(error); save(BATCH/'errors'/(identifier+'.json'),error)
            if i%10==0 or i==len(pending):
                message=f'{phase}: {i}/{len(pending)} computed; errors={len(errors)}; seconds={time.monotonic()-start:.1f}'
                print(message,flush=True)
                with (BATCH/'execution.log').open('a',encoding='utf-8') as stream: stream.write(message+'\n')
    check={'phase':phase,'planned_n':len(cases),'newly_computed_n':len(pending),
           'available_n':sum((destination/(c['id']+'.json')).exists() for c in cases),
           'errors':errors,'passed':not errors,'new_model_calls':0,'seconds':time.monotonic()-start,
           'input_hashes_unchanged':all(digest(ROOT/name)==value for name,value in lock['files'].items())}
    save(BATCH/(phase+'-execution.json'),check)
    return check


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('register','pilot','all'))
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    result=register() if args.action=='register' else execute(args.action,args.workers)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result.get('passed',True) else 1


if __name__=='__main__':
    raise SystemExit(main())
