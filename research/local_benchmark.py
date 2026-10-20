"""Offline engineering replay of existing pilot cases, not a fresh benchmark."""
import hashlib
import json
import statistics
import sys
import subprocess
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research')); sys.path.insert(0,str(ROOT/'solver'))
from pilot import BANK, read, save, history, score
from verify_oracles import as_app
from inverse_local import analyze

OUT=ROOT/'outputs/inverse/local-0.1-20261020'
SOURCE=ROOT/'outputs/inverse/pilot-20261019-v3/oracle/private-bases.json'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    protocol={'version':'0.1.0','sourceSha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              'K':20,'noiseGapBudgets':[0,.15],'configurationCount':6,'modelCalls':0,
              'purpose':'engineering replay; previously used synthetic data; no new population-effect claim',
              'selection':'3-fold validation inside training only; grid 0/.001/.01/.1; no text or hidden truth in fitting'}
    save(OUT/'protocol.json',protocol)
    rows=read(OUT/'results.json') if (OUT/'results.json').exists() else []
    done={(r['base'],r['noise']) for r in rows}
    for base in read(SOURCE):
        for noise in protocol['noiseGapBudgets']:
            if (base['id'],noise) in done: continue
            # Pyomo/HiGHS resources are released with each process. Checkpoints survive failure.
            child=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--case',base['id'],str(noise)],capture_output=True,text=True,encoding='utf-8',timeout=300)
            if child.returncode: raise RuntimeError(child.stderr[-2000:])
            row=json.loads(child.stdout)
            rows.append(row);save(OUT/'results.json',rows)
            print(f"Local case {len(rows)}/12: {base['id']} noise={noise}; lambda={row['analysis']['selectedLambda']}; calls=0",flush=True)
    summary={'cases':len(rows),'modelCalls':0,'completed':sum(r['status']=='optimal' for r in rows),
             'certifiedRangeCount':sum(x['status']=='optimal' for r in rows for x in r['analysis'].get('identification',{}).get('ranges',[])),
             'meanNormalizedRegret':statistics.mean(r['metrics']['normalizedRegret'] for r in rows),
             'totalSeconds':sum(r['seconds'] for r in rows),'label':protocol['purpose']}
    save(OUT/'summary.json',summary)
    (OUT/'结果说明.txt').write_text(f"llm4orTT 0.1 本地功能验证\n完成 {summary['completed']}/{len(rows)} 个旧模拟案例的离线重算。\nDeepSeek调用：0次。\n已证明的参数范围：{summary['certifiedRangeCount']} 项。\n自动选择强度仅使用训练历史内部验证。\n这是旧数据的工程验证，不是新的独立科研成绩，也不是NLP4LP成绩。\n",encoding='utf-8-sig')
    print(json.dumps(summary),flush=True)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--case':
        base=next(b for b in read(SOURCE) if b['id']==sys.argv[2]);noise=float(sys.argv[3]);started=time.monotonic()
        result=analyze(as_app(history(base,20,noise)))
        row={'base':base['id'],'noise':noise,'seconds':time.monotonic()-started,'analysis':result['analysis'],
             'status':result['result']['status'],'theta':result['result']['theta'],'metrics':score(base,BANK,result['result']['theta'])}
        print(json.dumps(row,ensure_ascii=True,allow_nan=False))
    else: main()
