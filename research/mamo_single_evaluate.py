"""Score the complete exploratory single-item control; do not replace batched rows."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mamo_experiment import OUT,read,save,score

def main():
    records=read(OUT/'llm/single.json')
    truth={t['id']:t for t in read(OUT/'oracle/truth.json')}
    rows=[]
    for p in read(OUT/'public/problems.json'):
        if p['split']!='evaluation':continue
        row={'id':p['id'],'split':'evaluation','K':10,'noise':.1,'method':'llm_single','phase':'exploratory batch-sensitivity control'}
        try:
            r=records[str(p['id'])]
            if r['status']!='ok':raise ValueError(r['error'])
            estimate={'theta':[r['value']['theta'][f['id']] for f in p['bank']]}
            row.update(status='optimal',**estimate,**score(p,truth[p['id']],estimate))
        except Exception as e:row.update(status='failed',error=str(e))
        rows.append(row)
    save(OUT/'llm-single-scores.json',rows)
    print({'singleControlRows':len(rows),'failures':sum(r['status']!='optimal' for r in rows)},flush=True)

if __name__=='__main__':main()
