"""Archive exact research sources and verify every ZIP member without APIs."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'实验/决策契约研究_2026-10-21_01'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    paths=list((ROOT/'research').glob('decision_*.py'))
    paths += [ROOT/'research/verify_decision_bundle.py',Path(__file__)]
    paths += list((ROOT/'tests').glob('test_decision_*.py'))
    paths += [ROOT/'scripts/decision-contract-api.mjs',ROOT/'scripts/decision-report-qa.mjs',ROOT/'datasets/llm-grounding-v1/nl4opt-test.jsonl']
    for source in paths:
        destination=OUT/'source-snapshot'/source.relative_to(ROOT)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():raise ValueError('Snapshot already exists: '+str(destination))
        shutil.copyfile(source,destination)
    excluded={'manifest.json','seal-result.json','sealed-replay-verification.json','证据包.zip'}
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name not in excluded and '__pycache__' not in p.parts)
    manifest={'schema':'decision-study-evidence.v1','files':[{'path':p.relative_to(OUT).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)} for p in files],
              'exclusions':'Manifest, ZIP itself, post-seal verification and seal result are excluded to avoid circular hashing.'}
    manifestpath=OUT/'manifest.json'
    with manifestpath.open('x',encoding='utf-8') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
    archive=OUT/'证据包.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in files+[manifestpath]:z.write(p,p.relative_to(OUT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(files)+1
        for entry in manifest['files']:
            assert hashlib.sha256(z.read(entry['path'])).hexdigest()==entry['sha256']
        assert z.read('manifest.json')==manifestpath.read_bytes()
    result={'passed':True,'manifestFiles':len(files),'zipMembers':len(files)+1,'zipBytes':archive.stat().st_size,
            'zipSha256':digest(archive),'sourceSnapshots':len(paths),'newModelRequests':0}
    with (OUT/'seal-result.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result))

if __name__=='__main__':main()
