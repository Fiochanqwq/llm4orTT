"""No-network replay of the sealed primary scores and budget accounting."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from decision_contract_study import ROOT,OUT,read,candidate,mcnemar
from decision_geometry import compare_models
from decision_semantic_guard import repair_model as guard_v1
from decision_semantic_guard_v2 import repair_model as guard_v2

def verify():
    cases=read(OUT/'cases.private.json');requests=0;decisions=0
    protocol=read(OUT/'protocol.json')
    for split in ('development','heldout'):
        cohort=[c for c in cases if c['split']==split]
        assert [c['id'] for c in cohort]==protocol['frozenCaseIds'][split]
        stored={r['id']:r for r in read(OUT/f'{split}-scores.json')}
        score={a:[] for a in ('A','B','abstract','witness')}
        for case in cohort:
            for arm in score:
                got=candidate(case,arm);expected=stored[case['id']]['arms'][arm]
                assert got['valid']==expected['valid']
                if got['valid']:
                    comparison=compare_models(case['reference'],got['model'])
                    assert comparison==expected['comparison']
                    success=comparison['feasible_sets_equal'] and comparison['optimal_faces_equal']
                else: success=False
                assert success==expected['success'];score[arm].append(success);decisions+=1
        summary=read(OUT/f'{split}-summary.json')
        assert summary['scores']=={a:sum(v) for a,v in score.items()}
        assert summary['primary']==mcnemar(score['abstract'],score['witness'])
    oldids={c['id'] for c in cases};newcases=read(OUT/'transfer-cases.private.json')
    assert not oldids & {c['id'] for c in newcases}
    assert len(newcases)==len({c['id'] for c in newcases})==11
    guard_scores={r['id']:r for r in read(OUT/'semantic-guard-scores.json')}
    for case in [c for c in cases if c['split']=='heldout']:
        got=candidate(case,'A');stored=guard_scores[case['id']]
        if got['valid']:
            patch=guard_v1(case['text'],case['variables'],got['model'])
            assert patch==stored['patch']
            assert compare_models(case['reference'],patch['model'])==stored['comparison']
    transfer_scores={r['id']:r for r in read(OUT/'transfer-scores.json')}
    for case in newcases:
        stored=transfer_scores[case['id']]
        raw=read(OUT/'network'/('transfer_'+case['id']+'_A.result.json'))
        if stored['valid']:
            model=json.loads(raw['text']);patch=guard_v2(case['text'],case['variables'],model)
            assert patch==stored['patch']
            assert compare_models(case['reference'],model)==stored['before']
            assert compare_models(case['reference'],patch['model'])==stored['after']
    events=[json.loads(x) for x in (OUT/'calls.jsonl').read_text('utf-8').splitlines()]
    starts={e['id']:e for e in events if e['event']=='started'}
    ends={e['id']:e for e in events if e['event']=='finished'}
    assert len(starts)==sum(e['event']=='started' for e in events)==300
    assert set(starts)==set(ends)
    assert sorted(e['sequence'] for e in starts.values())==list(range(1,301))
    for identifier,event in starts.items():
        prefix=OUT/'network'/identifier
        request=read(Path(str(prefix)+'.request.json'));result=read(Path(str(prefix)+'.result.json'))
        # JSON.stringify-compatible encoding of JSON data: request fields contain no floats.
        encoded=json.dumps(request,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        assert hashlib.sha256(encoded).hexdigest()==event['promptSha256']
        assert result['status']==ends[identifier]['status']
        requests+=1
    checked=0
    manifest=OUT/'manifest.json'
    if manifest.exists():
        for entry in read(manifest)['files']:
            p=(OUT/entry['path']).resolve()
            assert p.is_relative_to(OUT.resolve())
            assert hashlib.sha256(p.read_bytes()).hexdigest()==entry['sha256'],entry['path']
            checked+=1
    return {'passed':True,'newModelRequests':0,'recomputedPrimaryArmDecisions':decisions,
            'recomputedGuardCases':len(guard_scores),'recomputedTransferCases':len(transfer_scores),
            'uniqueAttemptedRequests':requests,'cohortsDisjoint':True,'manifestFilesChecked':checked}

if __name__=='__main__':print(json.dumps(verify(),indent=2))
