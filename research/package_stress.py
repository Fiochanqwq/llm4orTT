"""Publish an explicit allowlist of public research evidence; preserve old archives."""
import hashlib,json,re,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/inverse/public-stress-20261020-v2'
DEST=ROOT/'research/artifacts'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 for src in sorted((ROOT/'datasets/stress-public-v1').iterdir()):
  if src.is_file():
   dst=OUT/'source-data'/src.name;dst.parent.mkdir(exist_ok=True);shutil.copy2(src,dst)
 shutil.copy2(ROOT/'datasets/stress-public-v1/download-manifest.json',OUT/'download-manifest.json')
 old=ROOT/'outputs/inverse/public-stress-20261020-v1'
 if old.exists():shutil.copytree(old,OUT/'interrupted-v1',dirs_exist_ok=True)
 shutil.copy2(ROOT/'datasets/mamo/LICENSE',OUT/'source-data/MAMO-LICENSE')
 (OUT/'DATA-ATTRIBUTION.txt').write_text(
  'OR-Library mknap1: J. E. Beasley; seven Petersen research-development selection instances. MIT notice is source-data/ORLIB-LICENSE.html; preserve it with redistributed data.\n'
  'NETLIB afiro/adlittle: historical NETLIB LP collection, fixed HiGHS v1.15.1 mirror. Source URLs and byte hashes in download-manifest.json. HiGHS software licensing is not asserted to replace historical data attribution.\n'
  'TSPLIB95: Gerhard Reinelt and original benchmark contributors; gr17/gr21/gr24/fri26 from the official Heidelberg site. Source URLs and published best values retained. No blanket MIT license is asserted for these data.\n'
  'Historical MAMO source44 derived witness only: Xuhan Huang, Qingning Shen, Yan Hu, Anningzhe Gao, Benyou Wang; https://github.com/FreedomIntelligence/Mamo revision 2c91069dee5c1e4db4b899eb176ec987d0251bb3; CC BY-SA 4.0, see source-data/MAMO-LICENSE. Kept separate from new results.\n'
  'New transformations: masked objective coefficients, generated contexts/histories, numerical inverse fits and diagnostic witnesses. No private conversations, API credentials or personal data included. Project code retains LICENSE.\n',encoding='utf8')
 names=['research/stress_sources.py','research/stress_protocol.json','research/stress_public.py','research/stress_analyze.py','research/stress_crosscheck.py','research/stress_mechanisms.py','research/stress_report.py','research/package_stress.py','research/REPRODUCE_STRESS.txt','test/stress-public-test.py','scripts/stress-public.mjs','scripts/stress-resume.mjs','scripts/stress-qa.mjs','server/python-runtime.mjs','docs/solver-lock.json','LICENSE']
 names+=['research/stress_control_addendum.json','research/stress_control.py']
 for name in names:
  p=OUT/'reproduction'/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
 shutil.copy2(ROOT/'research/REPRODUCE_STRESS.txt',OUT/'REPRODUCE.txt')
 patterns=[rb'sk-[A-Za-z0-9_-]{20,}',rb'gh[pousr]_[A-Za-z0-9_]{20,}',rb'github_pat_[A-Za-z0-9_]{20,}',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'Bearer [A-Za-z0-9_.-]{20,}']
 files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='artifact-files.json')
 for p in files:
  if p.suffix.lower() in ['.json','.jsonl','.txt','.html','.py','.mjs','.csv']:
   if any(re.search(pattern,p.read_bytes()) for pattern in patterns):raise ValueError('Possible credential '+str(p.relative_to(OUT)))
 manifest={'files':{p.relative_to(OUT).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in files}}
 (OUT/'artifact-files.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8');files.append(OUT/'artifact-files.json')
 archive=DEST/'public-stress-20261020-v2.zip'
 with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for p in files:z.write(p,p.relative_to(OUT).as_posix())
 with zipfile.ZipFile(archive) as z:
  assert z.testzip() is None
  for name,r in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==r['sha256']
 info={'file':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size,'archivedFiles':len(files),'credentialPatternScan':'passed; only public research evidence allowlist','manifestInside':'artifact-files.json'}
 (DEST/'public-stress-20261020-v2.manifest.json').write_text(json.dumps(info,indent=2),encoding='utf8')
 print(json.dumps(info))
if __name__=='__main__':main()
