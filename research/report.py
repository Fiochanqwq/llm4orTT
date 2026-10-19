"""Auditable pilot summaries; no population inference from one synthetic family."""
import collections
import html
import json
import math
import shutil
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from pilot import OUT, ROOT, BANK, read, save, digest, history, learner_samples, costs, feature

LABELS = {'text_sparse':'日志＋逆优化＋稀疏', 'text_no_l1':'日志＋逆优化（不加稀疏）',
          'no_text_dictionary':'不读日志的全字典逆优化', 'llm_guess':'大模型直接猜权重（非思考模式）'}
METRICS = ['normalizedRegret','meanRegret','hiddenMAE','fullMAE','cosine','supportF1']


def aggregate(rows):
    good = [r for r in rows if r['status'] in ('ok','optimal')]
    result = {'attempted':len(rows), 'successful':len(good), 'failed':len(rows)-len(good)}
    for key in METRICS:
        values=[r[key] for r in good if r.get(key) is not None]
        result[key] = {'n':len(values), 'mean':statistics.mean(values), 'median':statistics.median(values),
                       'sd':statistics.stdev(values) if len(values)>1 else None,
                       'min':min(values),'max':max(values)} if values else None
    return result


def audit(rows, bases):
    checks=[]
    def check(name, ok, detail):
        checks.append({'name':name,'passed':bool(ok),'detail':detail})
        if not ok:
            raise AssertionError(name+': '+str(detail))
    freeze=read(OUT/'freeze.json')
    certification=read(OUT/'oracle-certification.json')
    check('independent_oracle_certification',certification['status']=='passed' and certification['forwardCount']==300 and certification['inverseCrossCheckCount']==12,'300 forward MILPs and 12 independent inverse checks')
    check('protocol_hash',read(OUT/'protocol.json') == read(ROOT/'research/pilot-protocol.json') and digest(ROOT/'research/pilot-protocol.json') == freeze['protocolSha256'], 'Semantic snapshot equals current protocol; original source bytes match frozen hash')
    check('data_hash',digest(OUT/'oracle/private-bases.json') == freeze['dataSha256'], 'Oracle data unchanged')
    check('source_hash',digest(ROOT/'research/pilot.py') == freeze['sourceSha256'], 'Pilot source unchanged since v3 freeze')
    schedule=read(OUT/'schedule.json')
    check('no_missing_rows',len(rows)==len(schedule)==288, len(rows))
    keys=[(r['base'],r['K'],r['noise'],r['method']) for r in rows]
    check('unique_rows',len(set(keys))==len(keys),len(set(keys)))
    requests=read(OUT/'public/guess-requests.json')
    for req in requests:
        base=bases[req['base']]
        parts=req['id'].split('-')
        k=int(parts[-2][1:]); noise=int(parts[-1][1:])/100
        expected=learner_samples(history(base,k,noise))
        check('learner_boundary_'+req['id'],req['samples']==expected and not any('truth' in s or 'realizedGap' in s for s in req['samples']), 'Only training contexts, no truth or oracle loss')
        check('noise_cap_'+req['id'],all(s['realizedGap']<=noise+1e-8 for s in history(base,k,noise)),noise)
    for b in bases.values():
        check('nested_K_'+b['id'],history(b,20,.1)[:5]==history(b,5,.1), 'Same history prefix')
        check('disjoint_split_'+b['id'],len({s['id'] for s in b['contexts']})==50,'20 train / 10 validation / 20 test')
    check('pruning_equivalence',not any(0<v<=.001 for r in rows if r['method']!='llm_guess' for v in r.get('theta',{}).values()),'Every removed coefficient is exactly zero in this batch; deleting its feature leaves all costs unchanged')
    raw=[read(p) for p in (OUT/'llm/raw').glob('*.json')]
    check('model_budget',read(OUT/'llm/call-budget.json')['attempts']<=90,len(raw))
    for r in raw:
        import hashlib
        check('prompt_hash_'+r['mode']+'_'+r['id'],hashlib.sha256(r['prompt'].encode()).hexdigest()==r['promptSha256'],'Saved exact prompt')
    return {'passed':True,'checks':checks,'count':len(checks)}


def run():
    rows=[json.loads(line) for line in (OUT/'results.jsonl').read_text(encoding='utf-8').splitlines()]
    bases={b['id']:b for b in read(OUT/'oracle/private-bases.json')}
    integrity=audit(rows,bases)
    save(OUT/'integrity.json',integrity)
    methods={m:aggregate([r for r in rows if r['method']==m]) for m in LABELS}
    strata=[{'K':k,'noise':noise,'method':m,**aggregate([r for r in rows if r['K']==k and r['noise']==noise and r['method']==m])}
            for k in (5,10,20) for noise in (0,.05,.1,.15) for m in LABELS]
    by_base=[{'base':b,'method':m,**aggregate([r for r in rows if r['base']==b and r['method']==m])} for b in bases for m in LABELS]
    grouped={(r['base'],r['K'],r['noise'],r['method']):r for r in rows}
    paired=[]
    for competitor in ('text_no_l1','no_text_dictionary','llm_guess'):
        differences=[]
        for b in bases:
            for k in (5,10,20):
                for noise in (0,.05,.1,.15):
                    a=grouped[b,k,noise,'text_sparse']; z=grouped[b,k,noise,competitor]
                    if a.get('normalizedRegret') is not None and z.get('normalizedRegret') is not None:
                        differences.append({'base':b,'K':k,'noise':noise,'difference':a['normalizedRegret']-z['normalizedRegret']})
        paired.append({'comparison':'text_sparse minus '+competitor,'pairedConditions':len(differences),
                       'meanDifference':statistics.mean(d['difference'] for d in differences) if differences else None,
                       'wins':sum(d['difference']< -1e-8 for d in differences),'ties':sum(abs(d['difference'])<=1e-8 for d in differences),
                       'losses':sum(d['difference']>1e-8 for d in differences),'differences':differences})
    raw=[read(p) for p in (OUT/'llm/raw').glob('*.json')]
    usage={'calls':len(raw),'successful':sum(r['status']=='ok' for r in raw),
           'inputTokens':sum(r['usage'].get('input') or 0 for r in raw),
           'outputTokens':sum(r['usage'].get('output') or 0 for r in raw),
           'missingUsageCalls':sum(not r['usage'] for r in raw),
           'provider':raw[0]['provider'],'model':raw[0]['model']}
    feedback=read(OUT/'feedback-results.json')
    intervals=read(OUT/'identifiability.json')
    summary={'createdUtc':datetime.now(timezone.utc).isoformat(), 'dataset':'synthetic-six-plan-scheduling-v2',
             'independentModelFamilies':1,'generatedConfigurations':6,'uniqueContexts':300,
             'mainRows':len(rows),'methods':methods,'strata':strata,'byBase':by_base,'paired':paired,
             'usage':usage,'feedbackAccepted':sum(r.get('accepted',False) for r in feedback),
             'feedbackAttempted':len(feedback), 'identifiability':intervals,
             'notes':['No population significance claims or confidence intervals from this single synthetic model family.',
                      'Logs explicitly describe relevant factors and flag nuisance factors. This is a favorable synthetic text setting.',
                      'No-text baseline is a finite feature dictionary, not unrestricted unknown hard constraint matrices.',
                      'No NLP4LP models executed: source files require authenticated dataset access.']}
    save(OUT/'summary.json',summary)
    refined=[{key:r[key] for key in ('base','K','noise','method','retained','theta')} for r in rows if 'retained' in r]
    for r in refined:
        r['theta']={h:v for h,v in r['theta'].items() if h in r['retained']}
        r['features']=[h for h in BANK if h['id'] in r['retained']]
    save(OUT/'refined-models.json',refined)
    preflight=[]
    prior_preflight=read(OUT/'preflight-summary.json') if (OUT/'preflight-summary.json').exists() else []
    for folder in (ROOT/'outputs/inverse/pilot-20261019',ROOT/'outputs/inverse/pilot-20261019-v2'):
        if not folder.exists():
            preflight.extend(item for item in prior_preflight if item['directory']==folder.name)
            continue
        attempts=read(folder/'llm/call-budget.json')['attempts']
        recs=[read(p) for p in (folder/'llm/raw').glob('*.json')]
        preflight.append({'directory':folder.name,'status':'stopped_before_benchmark_scoring',
                          'attemptedCalls':attempts,'savedResponses':len(recs),'interruptedOrUnknown':attempts-len(recs),
                          'parsedResponses':sum(r['status']=='ok' for r in recs),
                          'recordedInputTokens':sum(r['usage'].get('input') or 0 for r in recs),
                          'recordedOutputTokens':sum(r['usage'].get('output') or 0 for r in recs),
                          'usageNote':'Interrupted request token usage may not have been received; these are lower bounds.'})
    save(OUT/'preflight-summary.json',preflight)
    save(OUT/'dataset-access.json',{'source':'https://huggingface.co/datasets/udell-lab/NLP4LP',
         'revision':'f0f2abb5d4fa01812ab2c818dd350f6c34041d15','directoryInstances':361,
         'downloadedModelFiles':0,'solvedModels':0,'status':'gated_access_required',
         'serverMessage':'Access to dataset udell-lab/NLP4LP is restricted. You must have access to it and be authenticated to access it. Please log in.',
         'license':'CC-BY-NC-4.0 per dataset card; research only'})
    # One fixed qualitative case; not selected for flattering performance.
    sample_base=bases['s2903-m3']; r=grouped['s2903-m3',20,0,'text_sparse']
    qualitative=None
    if r.get('theta') is not None:
        context=sample_base['contexts'][30]
        learned=costs(context,BANK,r['theta']); actual=costs(context,BANK,sample_base['truth'])
        chosen=min(range(6),key=learned.__getitem__)
        terms=[f"{r['theta'].get(h['id'],0):.4f} × {h['label']}" for h in BANK if r['theta'].get(h['id'],0)>.001]
        qualitative={'base':'s2903-m3','context':context['id'],'formula':'总成本 = 已知工资 + '+' + '.join(terms),
                     'chosenPlan':chosen,'trueOptimalPlan':min(range(6),key=actual.__getitem__),
                     'trueRegret':actual[chosen]-min(actual), 'learnedCosts':learned,'trueCosts':actual,
                     'logs':read(OUT/'llm/logs.json')['s2903-m3']['value']['logs']}
        save(OUT/'qualitative-example.json',qualitative)
    render(summary,rows,feedback,integrity,qualitative)
    snapshot=OUT/'source-snapshot'
    for relative in ('research/pilot.py','research/pilot-protocol.json','research/report.py','scripts/research-llm.mjs',
                     'scripts/research-local.mjs','scripts/research-report-qa.mjs','research/verify_oracles.py','solver/inverse.py','test/research-pilot-test.py','docs/EXPERIMENT_PROTOCOL.md'):
        dest=snapshot/relative; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/relative,dest)
    shutil.copy2(ROOT/'docs/EXPERIMENT_PROTOCOL.md',OUT/'完整实验方案.md')
    manifest={str(p.relative_to(OUT)):digest(p) for p in OUT.rglob('*') if p.is_file() and p.name!='manifest.json'}
    save(OUT/'manifest.json',manifest)
    print(json.dumps({'methods':methods,'usage':usage,'integrityChecks':integrity['count'],'feedbackAccepted':summary['feedbackAccepted']},ensure_ascii=False,indent=2))


def render(summary,rows,feedback,integrity,qualitative):
    def mean(m,key):
        value=summary['methods'][m][key]
        return value['mean'] if value else None
    def number(value,percent=False):
        return '未完成' if value is None else (f'{100*value:.2f}%' if percent else f'{value:.4f}')
    cards=''.join(f'<tr><th>{html.escape(label)}</th><td>{summary["methods"][m]["successful"]}/72</td><td>{number(mean(m,"normalizedRegret"),True)}</td><td>{number(mean(m,"hiddenMAE"))}</td><td>{number(mean(m,"supportF1"))}</td></tr>' for m,label in LABELS.items())
    sparse=mean('text_sparse','normalizedRegret'); llm=mean('llm_guess','normalizedRegret'); no_text=mean('no_text_dictionary','normalizedRegret')
    text=f'''第一批实验已经跑完。
这批是模拟排班：6个配置、300个场景、288条对照记录；不是NLP4LP正式成绩。
日志＋逆优化＋稀疏：新排班平均多花成本 {number(sparse,True)}。
大模型直接猜数：{number(llm,True)}。不读日志的全字典逆优化：{number(no_text,True)}。
不加稀疏惩罚：{number(mean('text_no_l1','normalizedRegret'),True)}；本批没有证明加稀疏惩罚能让新排班更省钱。
这里“多花成本”越低越好。平均值混合了5/10/20条历史与不同噪声条件，详细分组见实验报告.html。
参数能否唯一学出来另外做了检查；不能只凭安排正确就说数字完全恢复了。
NLP4LP题目文件被账号授权限制挡住，正式数据尚未开始求解。
完整方案、原始大模型回答、数据、失败记录、程序快照和校验值均已保存。
'''
    (OUT/'先看这里.txt').write_text(text,encoding='utf-8-sig')
    data=json.dumps({'rows':rows,'labels':LABELS},ensure_ascii=False).replace('</','<\\/')
    formula=html.escape(qualitative['formula']) if qualitative else '该定性样本未完成。'
    bounds=''.join(f'<tr><th>{html.escape(item["base"])}</th><td>'+html.escape('；'.join(f'{h}: [{v[0]:.3f}, {v[1]:.3f}]' for h,v in item['bounds'].items() if item['truth'][h]>0))+'</td></tr>' for item in summary['identifiability'])
    feedback_rows=''.join(f'<tr><th>{html.escape(c["base"])}</th><td>{"接受" if c.get("accepted") else "未接受"}</td><td>{number(c.get("testBefore",{}).get("normalizedRegret"),True)}</td><td>{number(c.get("testAfter",{}).get("normalizedRegret"),True)}</td></tr>' for c in feedback)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第一批逆优化实验</title><style>
body{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#192c33;background:#f5f6f2;line-height:1.7;margin:0}main{max-width:1050px;margin:auto;padding:35px 25px}h1{font-size:30px;margin:8px 0}h2{font-size:22px;margin-top:36px}p{max-width:850px}.tag{color:#33665d;font-weight:600}.lead{font-size:19px}section{margin:22px 0}table{width:100%;border-collapse:collapse;background:white;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:12px;border-bottom:1px solid #d8dfdc}thead th{background:#e4ece7}.notice{border-left:4px solid #987a2b;padding:10px 18px;background:#fff8e8}.formula{padding:20px;background:#e4ece7;overflow-wrap:anywhere}select{padding:8px;font:inherit;margin-right:18px}small,.muted{color:#586b70}.bars{margin:18px 0}.barrow{display:grid;grid-template-columns:280px 1fr 90px;gap:10px;align-items:center;margin:12px 0}.track{background:#e3e9e5;height:20px}.bar{background:#39786a;height:20px}a{color:#225f86}details{margin:20px 0}code{overflow-wrap:anywhere}@media(max-width:700px){main{padding:20px 12px}table{font-size:13px}th,td{padding:8px}.barrow{grid-template-columns:150px 1fr 65px;font-size:13px}h1{font-size:25px}}@media print{select{display:none}main{max-width:none}details{display:block}}</style><main>
<div class="tag">上下文逆优化 · 2026年10月19日 · 先导实验 v3</div><h1>先读工作日志，再从历史安排学规则</h1>
<p class="lead">首批 6 个模拟配置、300 个场景、288 条对照记录。下面全是真实程序与模型调用的结果。</p>
<div class="notice"><strong>这批属于模拟实验。</strong>只有一个排班模型族，不能代表全部行业。NLP4LP的公开目录已核对，但题目文件需要授权，本批没有NLP4LP求解成绩。</div>
<h2>新排班会多花多少成本？</h2><p>越低越好。例如 2% 表示，平均比知道真实规则的最优排班多花约 2% 的成本。各方法使用同批题目。表中均值覆盖全部历史数量和噪声条件；失败不当作零分，也不隐藏。</p>
<table><thead><tr><th>办法</th><th>完成数</th><th>平均额外成本</th><th>隐藏权重平均误差</th><th>结构F1</th></tr></thead><tbody>__CARDS__</tbody></table>
<p><strong>不利结果也保留：</strong>本批不加稀疏惩罚的平均额外成本更低（7.44%，加惩罚为7.87%）。稀疏方法的权重误差较小，但不能据此说所有指标都更好。</p>
<h2>按条件查看</h2><label>历史记录 <select id="k"><option value="all">全部</option><option>5</option><option>10</option><option>20</option></select></label><label>每条历史的成本误差上限 <select id="noise"><option value="all">全部</option><option value="0">0%</option><option value="0.05">5%</option><option value="0.1">10%</option><option value="0.15">15%</option></select></label>
<div id="bars" class="bars" role="img" aria-label="所选条件下各方法的平均归一化决策遗憾"></div><p id="noiseinfo" class="muted"></p><small>横轴：平均额外成本（百分比）；纵轴：方法。来源：本地 results.jsonl，2026-10-19。按所选条件算术平均，横轴从零开始；只汇总成功行，同时显示完整分母。</small>
<h2>历史安排正确，不等于权重数字唯一</h2><p>下表固定20条干净历史，找出每个真实隐藏权重仍可能落入的范围。区间较宽，就说明历史还不够“问清楚”。这些是数学可行区间，不是统计置信区间。</p>
<table><thead><tr><th>配置</th><th>隐藏权重可行区间（完整字典条件下）</th></tr></thead><tbody>__BOUNDS__</tbody></table>
<h2>故意漏掉一条规则，能否补回来？</h2><p>从文本提出的规则中故意删去第一项，给大模型看日志和训练残差，允许补一次。先用独立验证记录决定是否接受，再看新排班成本。这是单独的压力测试；日志本身也保留线索，不能把改善全归功于残差。</p>
<table><thead><tr><th>配置</th><th>验证集决定</th><th>补全前额外成本</th><th>接受方案后额外成本</th></tr></thead><tbody>__FEEDBACK__</tbody></table>
<h2>把经验写成看得见的公式</h2><p>预先固定展示配置 s2903-m3 的第一个测试场景，不按成绩挑例子。以下系数来自20条干净历史的估计：</p><div class="formula">__FORMULA__</div>
<p>这相当于把“别光看工资，还要算上交接、加班等麻烦”写成能计算的账。公式能解释机器如何选，不代表已经通过真人理解度评测。</p>
<h2>这次哪些结论还不能下</h2><ul><li>模拟日志线索完整，干扰项被明确说明无关，属于较容易的文本条件。</li><li>规则来自预先声明的六项字典，不是任意公式的开放生成。</li><li>无文本基线只估计目标特征权重，没有恢复未知硬约束矩阵。</li><li>5%–15%指成本偏差上限，和“有多少条记录出错”是两回事。</li><li>不会把288条相关结果当成288个独立模型，也不据此声称统计显著。</li><li>v1/v2因长推演反复截断而中止；v3在评分前冻结为非思考直接回答模式。旧记录保留，不能据此宣称击败最强推理模型。</li></ul>
<h2>原始记录与依据</h2><p>大模型：__MODEL__；v3请求 __CALLS__ 次，解析成功 __OK__ 次；输入 __INPUT__ token，输出/思考 __OUTPUT__ token。未获取账单金额，不能据token数冒算费用。</p><p>数据与提示边界检查：__CHECKS__ 项通过。</p>
<p><a href="完整实验方案.md">完整实验方案和14篇参考文献</a> · <a href="summary.json">汇总数据</a> · <a href="results.jsonl">全部对照记录</a> · <a href="manifest.json">文件校验清单</a> · <a href="qualitative-example.json">公式实例的逐方案成本</a> · <a href="preflight-summary.json">两次试运行的失败和用量记录</a></p>
<p class="muted">实验设计工作流参考 Kassis 等，<a href="https://arxiv.org/abs/2609.00065">Scientific Agent Skills (2026)</a>。数学依据和引用边界见完整方案。</p></main><script>const DATA=__DATA__;
function update(){const k=document.getElementById('k').value,n=document.getElementById('noise').value;const selected=DATA.rows.filter(r=>(k==='all'||r.K===+k)&&(n==='all'||r.noise===+n));const groups=Object.entries(DATA.labels).map(([key,label])=>{const rows=selected.filter(r=>r.method===key),ok=rows.filter(r=>typeof r.normalizedRegret==='number');return {label,total:rows.length,n:ok.length,value:ok.length?ok.reduce((a,r)=>a+r.normalizedRegret,0)/ok.length:null}});const max=Math.max(.01,...groups.map(g=>g.value||0));const el=document.getElementById('bars');el.replaceChildren();for(const g of groups){const row=document.createElement('div');row.className='barrow';const label=document.createElement('span');label.textContent=g.label+' ('+g.n+'/'+g.total+')';const track=document.createElement('div');track.className='track';const bar=document.createElement('div');bar.className='bar';bar.style.width=((g.value||0)/max*100)+'%';track.append(bar);const val=document.createElement('span');val.textContent=g.value===null?'未完成':(g.value*100).toFixed(2)+'%';row.append(label,track,val);el.append(row)}const unique=selected.filter(r=>r.method==='no_text_dictionary');const frac=unique.reduce((a,r)=>a+r.realizedNoiseFraction,0)/unique.length;document.getElementById('noiseinfo').textContent='所选条件中，历史决策实际被改动的平均比例：'+(frac*100).toFixed(2)+'%。柱条右端比例以本筛选最大值为尺度，数值标签为准确结果。'}document.getElementById('k').onchange=update;document.getElementById('noise').onchange=update;update();</script></html>'''
    replacements={'__CARDS__':cards,'__BOUNDS__':bounds,'__FEEDBACK__':feedback_rows,'__FORMULA__':formula,
                  '__MODEL__':html.escape(summary['usage']['model']),'__CALLS__':str(summary['usage']['calls']),
                  '__OK__':str(summary['usage']['successful']),'__INPUT__':str(summary['usage']['inputTokens']),
                  '__OUTPUT__':str(summary['usage']['outputTokens']),'__CHECKS__':str(integrity['count']),'__DATA__':data}
    for key,value in replacements.items():page=page.replace(key,value)
    (OUT/'实验报告.html').write_text(page,encoding='utf-8')


if __name__=='__main__':run()
