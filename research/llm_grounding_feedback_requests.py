"""Append compiler/fit-failure repair requests; no replacement of first-pass outcomes."""
import hashlib,json,random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/inverse/deepseek-grounding-20261020-v1'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
cfg=read(OUT/'protocol.json');requests=read(OUT/'requests/feedback.json');existing={r['id'] for r in requests};added=[]
for meta in read(OUT/'models.json'):
    sid=meta['id'];public=read(OUT/'public'/f'{sid}.json')
    logs=read(OUT/'llm/logs'/f'{sid}.json')
    if logs['status']!='ok':continue
    proposal=read(OUT/'llm/proposal'/f'{sid}.json')
    for seed in cfg['seeds']:
        job=read(OUT/'jobs'/f'{sid}-s{seed}.json')
        contexts=read(OUT/'contexts'/f'{sid}-s{seed}.json')
        for cap in cfg['noiseCaps']:
            rid=f'{sid}-s{seed}-n{cap}'
            if rid in existing:continue
            rr=next((r for r in job['rows'] if r['method']=='ds_io' and r['K']==10 and r['noise']==cap),None)
            if rr is None or rr['status']=='complete':continue
            requests.append({'id':rid,'problemId':sid,'problem':public,'logs':logs['value']['logs'],
                             'features':proposal.get('value',{}).get('features',[]),'weights':None,
                             'compilerOrFitError':rr.get('error','first-pass incomplete'),
                             'topTrainingResiduals':[],
                             'history':[{'knownBase':s['base'],'observedDecision':s.get('decisions',{}).get(str(cap))} for s in contexts[:10]],
                             'repairInstruction':'Repair the compiler/fit error and return the complete valid feature list. Unknown prices require placeholders, not execution. No test data is provided.'})
            added.append(rid)
random.Random(20261020).shuffle(requests)
assert len({r['id'] for r in requests})==len(requests)
write(OUT/'requests/feedback.json',requests)
write(OUT/'feedback-repair-amendment.json',{
    'stage':'after first-pass compilation/fit outcomes, before any feedback API output',
    'change':'One bounded feedback call also offered to first-pass compiler/fit failures, using the recorded error and training histories only',
    'reason':'A compiler failure cannot supply residuals. Leaving it without repair would prevent the requested automatic reconstruction loop from attempting recovery.',
    'addedRequestIds':added,'firstPassOutcomesPreserved':True,'testScoresSent':False,
    'label':'exploratory failure-repair extension; does not retroactively improve the first-pass method',
    'requestSha256':hashlib.sha256((OUT/'requests/feedback.json').read_bytes()).hexdigest()})
print(json.dumps({'feedbackRequests':len(requests),'addedFailureRepairs':len(added)}))
