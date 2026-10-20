"""Allowlisted public-evidence packaging; no application account files."""
import hashlib,json,re,shutil,subprocess,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/inverse/deepseek-grounding-20261020-v1'
DELIVERY=ROOT/'实验/逆优化实验_2026-10-20_DeepSeek文本闭环'
ART=ROOT/'research/artifacts/deepseek-grounding-20261020-v1.zip'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def copy(source,dest):
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
def prepare():
    code=[*ROOT.glob('research/llm_grounding*.py'),*ROOT.glob('research/llm_grounding*.json'),
          *ROOT.glob('scripts/llm-grounding-*.mjs'),*ROOT.glob('test/llm-grounding-*.py'),
          ROOT/'research/verify_llm_grounding_bundle.py',ROOT/'research/mamo_experiment.py',
          ROOT/'research/REPRODUCE_LLM_GROUNDING.txt',ROOT/'scripts/llm-grounding-report-qa.mjs']
    for p in code:
        copy(p,OUT/'reproduction'/p.relative_to(ROOT))
    for p in (ROOT/'datasets/llm-grounding-v1').iterdir():
        if p.is_file():copy(p,OUT/'source-data/llm-grounding-v1'/p.name)
    for name in ['LICENSE','mamo_complex_lp.jsonl','README.md','revision.json','source-manifest.json']:
        copy(ROOT/'datasets/mamo'/name,OUT/'source-data/mamo'/name)
    copy(ROOT/'research/REPRODUCE_LLM_GROUNDING.txt',OUT/'REPRODUCE.txt')
    copy(ROOT/'research/verify_llm_grounding_bundle.py',OUT/'verify_bundle.py')
    copy(ROOT/'research/llm_grounding_references.json',OUT/'references.json')
    (OUT/'DATA-LICENSE.txt').write_text('''Source attribution and licensing — public research evidence

NL4Opt
NL4Opt Competition: Formulating Optimization Problems Based on Their
Natural Language Descriptions; Ramamonjison et al.
https://github.com/nl4opt/nl4opt-competition
revision49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea.
Official test annotations and the repository MIT license are enclosed in
source-data/llm-grounding-v1/nl4opt-test.jsonl and NL4OPT-LICENSE.

OptMATH
OptMATH: A Scalable Bidirectional Data Synthesis Framework for Optimization
Modeling; see official paper https://arxiv.org/abs/2502.11102.
https://github.com/optsuite/OptMATH
revisionf15bbc4477c70db85ad148df8bcc1b780bca0f8c.
Official benchmark and repository Apache2.0 license are enclosed in
source-data/llm-grounding-v1/OptMATH_Bench.json and OptMATH-LICENSE.
Original notices and their conditions apply to redistributed material.

MAMO
Huang, Shen, Hu, Gao and Wang; https://github.com/FreedomIntelligence/Mamo
revision2c91069dee5c1e4db4b899eb176ec987d0251bb3.
MAMO data and adaptations: CC BY-SA4.0. Enclosed LICENSE and README in
source-data/mamo retain the original conditions and attribution.

Changes made in this experiment
Deterministic source parsing; one original objective coefficient masked;
one synthetic hinge penalty added; contextual known costs varied;
synthetic optimal/bounded-gap histories generated; DeepSeek paraphrases
qualitative facts and proposes objective features/weights.
These are research augmentations, not original benchmark labels,
real human logs, original authors' results or author endorsement.
MAMO-derived adaptations remain subject to CC BY-SA4.0.
Code retains the repository's existing license status (UNLICENSED);
the presence of permissively licensed source data does not relicense
the project code. No account keys or private conversations are included.
''',encoding='utf8')
    save(OUT/'archive-scope.json',{'createdUtc':datetime.now(timezone.utc).isoformat(),
        'allowlist':'Only this experiment output directory, explicit reproduction scripts, and named public source files.',
        'excluded':'Application workspace state, credentials, .env, browser storage, private chat logs, .git.',
        'softwareVersion':'0.1.0','sourceBaseCommit':'ecc10e2ec56660e82862704ab5fcac0734e1ba0c',
        'rawAPIAttempts':397,'scheduledMainAndPromptRows':2912,'diagnosticRowsNotPooled':True})
    print('Prepared attribution, source data, reproduction snapshots.')
def archive():
    if DELIVERY.exists() or ART.exists():raise RuntimeError('Archive exists; never overwrite a batch')
    assert DELIVERY.resolve().is_relative_to((ROOT/'实验').resolve())
    files=[p for p in OUT.rglob('*') if p.is_file()]
    assert not any(p.suffix=='.lock' for p in files),'active writer lock exists'
    patterns=[rb'sk-[A-Za-z0-9_-]{20,}',rb'gh[pousr]_[A-Za-z0-9]{20,}',rb'github_pat_[A-Za-z0-9_]{30,}',
              rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    for p in files:
        if p.suffix.lower() in ['.json','.jsonl','.txt','.html','.py','.mjs','.md']:
            data=p.read_bytes()
            assert not any(re.search(pattern,data) for pattern in patterns),'possible credential in '+str(p.relative_to(OUT))
    # Freeze all included file hashes, including source and reproduction copies.
    hashes={p.relative_to(OUT).as_posix():sha(p) for p in sorted(files) if p.name!='CHECKSUMS.json'}
    save(OUT/'CHECKSUMS.json',{'algorithm':'SHA256','files':hashes,'selfExcluded':True})
    shutil.copytree(OUT,DELIVERY)
    ART.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(ART,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for p in sorted(DELIVERY.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(DELIVERY).as_posix())
    with zipfile.ZipFile(ART) as z:
        assert z.testzip() is None
        for name,digest in hashes.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
    save(ART.with_suffix('.manifest.json'),{'file':ART.name,'bytes':ART.stat().st_size,'sha256':sha(ART),
        'files':len(hashes)+1,'entryPoint':'完整研究报告.html','actualDeepSeekCalls':397,
        'counts':{'scheduled':2912,'complete':2707,'failed':101,'blockedSource':104},
        'privacyReview':'Explicit allowlist plus credential-pattern scan passed; no app workspace or user chat included.',
        'scope':'Frozen raw batch, exploratory prompt additions, and separate engineering/mechanism diagnostics.'})
    index=ROOT/'实验/先看这里.txt'
    addition='''\n\n6. 逆优化实验_2026-10-20_DeepSeek文本闭环
   入口：逆优化实验_2026-10-20_DeepSeek文本闭环\\完整研究报告.html
   简明说明：逆优化实验_2026-10-20_DeepSeek文本闭环\\实在结论.txt
   用途：397 次真实 DeepSeek API，NL4Opt、MAMO、OptMATH 三库；包含失败、文本消融、参数与决策错位、符号干预及复算证据。
   结论：文本有局部作用；尚未稳定胜过常数对照，不能声称价格恢复、反馈改进或真实隐性约束已获验证。
   此后阅读先看第 6 批；第 1 至 5 批保持原样。
'''
    with index.open('a',encoding='utf8') as f:f.write(addition)
    with (ROOT/'research/artifacts/README.txt').open('a',encoding='utf8') as f:
        f.write('''\n\nActual DeepSeek grounding: deepseek-grounding-20261020-v1.zip
Open 完整研究报告.html.397 real API attempts,27 admitted augmented public
problems from NL4Opt/MAMO/OptMATH,16 methods/ablations,2912 scheduled rows.
2707 completed,101 method failures,104 source-blocked rows.
Includes raw prompts/responses/usage, frozen contexts, all test decisions,
five figures, all failures, independent checks, original and clarified
prompt results, separately labeled solver repair and oracle-sign diagnosis.
Logs and soft penalties are synthetic. Text helps in a limited routing
cohort but constant-baseline superiority and reliable parameter recovery
are NOT established. Feedback did not improve complete paired cases.
Cost from token usage: CNY0.6574–1.3147, not an account invoice.
Verify offline with python verify_bundle.py. No new paid calls needed.
Read research/REPRODUCE_LLM_GROUNDING.txt and enclosed DATA-LICENSE.txt.
''')
    print(json.dumps({'delivery':str(DELIVERY),'zip':str(ART),'bytes':ART.stat().st_size,'files':len(hashes)+1},ensure_ascii=False))
if __name__=='__main__':
    {'prepare':prepare,'archive':archive}[sys.argv[1]]()
