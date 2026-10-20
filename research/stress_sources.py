"""Download fixed public benchmark inputs; retain every failed request."""
import hashlib,json,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DEST=ROOT/'datasets/stress-public-v1'
SOURCES={
 'mknap1.txt':'https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/mknap1.txt',
 'orlib-info.html':'https://people.brunel.ac.uk/~mastjjb/jeb/orlib/mknapinfo.html',
 'netlib-readme.txt':'https://netlib.org/lp/data/readme',
 'tsp-best.html':'https://comopt.ifi.uni-heidelberg.de/software/TSPLIB95/tsp/TSP-BEST.html',
 **{n+'.mps':'https://raw.githubusercontent.com/ERGO-Code/HiGHS/v1.15.1/check/instances/'+n+'.mps' for n in ['afiro','adlittle','blend']},
 **{n+'.tsp.gz':'https://comopt.ifi.uni-heidelberg.de/software/TSPLIB95/tsp/'+n+'.tsp.gz' for n in ['gr17','gr21','gr24','fri26']},
}
def main():
 DEST.mkdir(parents=True,exist_ok=True);records=[]
 for name,url in SOURCES.items():
  path=DEST/name;rec={'name':name,'url':url,'attempts':[]};start=time.perf_counter()
  if not path.exists():
   try:
    with urllib.request.urlopen(url,timeout=25) as r:body=r.read()
    path.write_bytes(body);rec['attempts'].append({'transport':'urllib','status':'ok'})
   except Exception as e:
    rec['attempts'].append({'transport':'urllib','status':'failed','error':str(e)})
    command="$ErrorActionPreference='Stop';$r=[Console]::In.ReadToEnd()|ConvertFrom-Json;Invoke-WebRequest -UseBasicParsing -Uri $r.url -OutFile $r.path -TimeoutSec 30"
    try:
     p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],input=json.dumps({'url':url,'path':str(path)}),capture_output=True,text=True,timeout=40)
     if p.returncode:raise RuntimeError(p.stderr[-1000:])
     rec['attempts'].append({'transport':'PowerShell','status':'ok'})
    except Exception as e:rec['attempts'].append({'transport':'PowerShell','status':'failed','error':str(e)})
  rec['seconds']=time.perf_counter()-start
  rec['status']='available' if path.exists() else 'unavailable'
  if path.exists():rec.update(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
  records.append(rec);print(json.dumps({'file':name,'status':rec['status'],'seconds':rec['seconds']}),flush=True)
  (DEST/'download-manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
