"""Curate public research evidence only. Never reads app settings or conversations."""
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/inverse/multifamily-20261020-v1'
DEST=ROOT/'research/artifacts'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    source=ROOT/'datasets/mamo'
    for name in ['LICENSE','mamo_complex_lp.jsonl','source-manifest.json']:
        folder=OUT/'source-data';folder.mkdir(exist_ok=True)
        shutil.copy2(source/name,folder/name)
    (OUT/'DATA-LICENSE.txt').write_text('MAMO source and derived research data: CC BY-SA 4.0.\nAuthors: Xuhan Huang, Qingning Shen, Yan Hu, Anningzhe Gao, Benyou Wang.\nhttps://github.com/FreedomIntelligence/Mamo\nCommit 2c91069dee5c1e4db4b899eb176ec987d0251bb3\nhttps://arxiv.org/abs/2405.13144\nChanges: parsed source models, controlled context perturbations, masked costs, synthetic logs and histories, local inverse estimates and audits.\nSee source-data/LICENSE for full terms. Project application code retains its original license.\nNo private user chats or API credentials are included.\n',encoding='utf8')
    names=['research/multifamily.py','research/multifamily_protocol.json','research/multifamily_analyze.py','research/multifamily_crosscheck.py','research/multifamily_report.py','research/multifamily_paper.py','research/package_multifamily.py','research/REPRODUCE_MULTIFAMILY.txt','test/multifamily-test.py','scripts/multifamily-local.mjs','scripts/multifamily-qa.mjs','server/python-runtime.mjs','docs/solver-lock.json','LICENSE']
    for name in names:
        p=OUT/'reproduction'/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
    credential_patterns=[rb'sk-[A-Za-z0-9_-]{20,}',rb'gh[pousr]_[A-Za-z0-9_]{20,}',rb'github_pat_[A-Za-z0-9_]{20,}',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'Bearer [A-Za-z0-9_.-]{20,}']
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='artifact-files.json')
    for p in files:
        if p.suffix.lower() in ['.json','.jsonl','.txt','.html','.py','.mjs','.csv']:
            data=p.read_bytes()
            if any(re.search(pattern,data) for pattern in credential_patterns):raise ValueError('Possible credential in '+str(p.relative_to(OUT)))
    manifest={'sourceRevision':'2c91069dee5c1e4db4b899eb176ec987d0251bb3','files':{p.relative_to(OUT).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in files}}
    (OUT/'artifact-files.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    files.append(OUT/'artifact-files.json')
    archive=DEST/'multifamily-20261020-v1.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in files:z.write(p,p.relative_to(OUT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,rec in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==rec['sha256']
    info={'file':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size,'archivedFiles':len(files),'credentialPatternScan':'passed; explicit public research file allowlist','sourceRevision':manifest['sourceRevision'],'manifestInside':'artifact-files.json'}
    (DEST/'multifamily-20261020-v1.manifest.json').write_text(json.dumps(info,indent=2),encoding='utf8')
    # Convenient GitHub preview of the manuscript without unpacking the data.
    shutil.copy2(OUT/'paper.pdf',DEST/'multifamily-paper-20261020.pdf')
    print(json.dumps(info))
if __name__=='__main__':main()
