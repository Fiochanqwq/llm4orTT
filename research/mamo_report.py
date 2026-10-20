"""Read all frozen outputs; produce paired, same-family descriptive analysis.
Run with the bundled authoring Python plus work/research/plot-deps (see runner).
"""
import collections
import hashlib
import html
import importlib.metadata
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'work/research/mplconfig'))
sys.path.insert(0,str(ROOT/'work/research/plot-deps'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
OUT=ROOT/'outputs/inverse/mamo-diet-20261020-v2'
LABELS={'zero_missing':'不恢复缺失成本','midpoint':'固定中点猜测','text_sparse':'日志＋逆优化＋稀疏',
        'text_no_l1':'去掉稀疏惩罚','no_text_sparse':'去掉文本筛选','no_text_no_l1':'无文本、无稀疏',
        'shuffled_text':'打乱文本候选','missing_text':'故意漏掉一项线索','local_feedback':'遗漏后本地补规则','llm_guess':'Flash批量猜（原对照）','llm_single':'Flash单题猜（附加对照）'}
METRICS=['normalizedRegret','hiddenMAE','cosine','supportF1']
COLORS=['#0072B2','#D55E00','#009E73','#CC79A7','#666666','#E69F00','#56B4E9','#444444','#946b32','#774477']


def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stats(rows):
    good=[r for r in rows if r['status']=='optimal']
    result={'attempted':len(rows),'completed':len(good),'failed':len(rows)-len(good)}
    for m in METRICS:
        vals=[r[m] for r in good]
        result[m]={'mean':statistics.mean(vals),'median':statistics.median(vals),'min':min(vals),'max':max(vals),
                   'sd':statistics.stdev(vals) if len(vals)>1 else None} if vals else None
    return result


def contrast(primary,left,right):
    a={r['id']:r for r in primary if r['method']==left and r['status']=='optimal'}
    b={r['id']:r for r in primary if r['method']==right and r['status']=='optimal'}
    ids=sorted(a.keys()&b.keys())
    if not ids:return {'left':left,'right':right,'n':0}
    delta=np.array([a[i]['normalizedRegret']-b[i]['normalizedRegret'] for i in ids])
    rng=np.random.default_rng(20261020)
    boot=delta[rng.integers(0,len(delta),size=(5000,len(delta)))].mean(axis=1)
    ci=np.quantile(boot,[.025,.975]).tolist()
    return {'left':left,'right':right,'n':len(ids),'meanDifference':float(delta.mean()),'ci95':ci,
            'wins':int(sum(delta < -1e-8)),'ties':int(sum(abs(delta)<=1e-8)),'losses':int(sum(delta>1e-8)),
            'definition':'left minus right; negative favors left; paired source-instance bootstrap; same-family descriptive interval',
            'pairs':[{'id':i,'left':a[i]['normalizedRegret'],'right':b[i]['normalizedRegret']} for i in ids]}


def audit(rows,problems):
    checks=[]
    def ck(name,ok,detail):
        checks.append({'name':name,'passed':bool(ok),'detail':detail})
        if not ok:raise ValueError('Audit failed: '+name)
    freeze=read(OUT/'freeze.json')
    for f,d in freeze['files'].items():ck('hash:'+f,digest(OUT/f)==d,d)
    ck('frozen executable source',digest(ROOT/'research/mamo_experiment.py')==freeze['sourceSha256'],'algorithm unchanged since freeze')
    expected=read(OUT/'schedule.json');normal=[r for r in rows if not r['method'].startswith('llm_')]
    key=lambda r:(r['id'],r['K'],r['noise'],r['method'])
    ck('complete fixed schedule',sorted(map(key,normal))==sorted(map(key,expected)),len(normal))
    ck('unique rows',len({key(r) for r in rows})==len(rows),len(rows))
    models=read(OUT/'oracle/models.json')
    signatures={json.dumps({k:m[k] for k in ['A','b','c']},sort_keys=True) for m in models}
    ck('distinct numeric source models',len(signatures)==len(models),len(signatures))
    truth={t['id']:t for t in read(OUT/'oracle/truth.json')}
    for p in problems:
        train={s['id'] for s in p['histories']['0']};test={s['id'] for s in p['testContexts']}
        ck('disjoint contexts:'+str(p['id']),not train&test and len(train)==20 and len(test)==20,'20 training + 20 held out')
        ck('no oracle fields in learner:'+str(p['id']),not any(w in p for w in ['truth','sourceAnswer','c','oracles']),list(p.keys()))
        for cap,gaps in truth[p['id']]['realizedGaps'].items():
            ck('noise bound:'+str(p['id'])+':'+cap,min(gaps)>=-1e-6 and max(gaps)<=float(cap)+1e-6,[min(gaps),max(gaps)])
    actual_proposals=read(OUT/'llm/proposals.json')
    fingerprint=hashlib.sha256(json.dumps(actual_proposals,sort_keys=True).encode()).hexdigest()
    ck('same proposals across all fits',all(read(f)['proposalFingerprint']==fingerprint for f in (OUT/'rows').glob('*.json')),fingerprint)
    raw=[read(p) for p in (OUT/'llm/raw').glob('*.json')]
    budget=read(OUT/'llm/call-budget.json')
    ck('paid request cap',len(raw)==budget['attempts']<=16,budget)
    extra=[read(p) for p in (OUT/'llm/single-raw').glob('*.json')]
    eb=read(OUT/'llm/single-call-budget.json')
    ck('separate supplementary request cap',len(extra)==eb['attempts']<=28,eb)
    ck('complete single-item cohort',len([r for r in rows if r['method']=='llm_single'])==31,'31 includes 3 reused diagnostic requests')
    raw+=extra
    cross=read(OUT/'formulation-crosscheck.json')
    ck('independent formulation checks',cross['status']=='passed' and len(cross['checks'])==4,'Pyomo and direct highspy, common solver')
    for r in raw:
        ck('prompt hash:'+r['mode']+str(r['ids']),hashlib.sha256(r['prompt'].encode()).hexdigest()==r['promptSha256'],r['ids'])
    return {'status':'passed','checks':checks,'checkCount':len(checks),'solverFailures':sum(r['status']!='optimal' for r in rows)}


def plot(rows,primary,contrasts):
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
        'font.size':10,'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
    fig,axs=plt.subplots(2,2,figsize=(14,10),layout='constrained')
    methods=['text_sparse','llm_single','no_text_sparse','text_no_l1','missing_text','local_feedback']
    ax=axs[0,0]
    for j,method in enumerate(methods):
        r=[x for x in primary if x['method']==method and x['status']=='optimal']
        vals=np.array([x['normalizedRegret']*100 for x in r])
        ax.scatter(np.full(len(vals),j)+np.linspace(-.13,.13,len(vals)),vals,s=16,alpha=.55,color=COLORS[j])
        ax.plot([j-.23,j+.23],[np.mean(vals)]*2,color='black',lw=2)
    ax.set_xticks(range(len(methods)),['日志+逆优化\n+稀疏','Flash单题猜\n（附加）','去掉文本','去掉稀疏','缺一条线索','本地补漏'],fontsize=9)
    ax.set_ylabel('新场景平均决策损失（%）');ax.set_title('A  主比较：每个点是一道公开题，黑线为均值')
    ax.set_ylim(bottom=0)
    for k,color,marker in zip([5,10,20],COLORS,['o','s','^']):
        ns=[0,.05,.1,.15]
        vals=[statistics.mean(r['normalizedRegret']*100 for r in rows if r['method']=='text_sparse' and r['K']==k and r['noise']==n and r['status']=='optimal') for n in ns]
        axs[0,1].plot([n*100 for n in ns],vals,color=color,marker=marker,label=f'K={k}')
    axs[0,1].set(xlabel='训练决策允许的近优差距上限（%）',ylabel='新场景平均决策损失（%）',title='B  噪声与历史样本量');axs[0,1].set_ylim(bottom=0);axs[0,1].legend()
    pairs=next(c['pairs'] for c in contrasts if c['right']=='llm_single')
    a=[r['right']*100 for r in pairs];b=[r['left']*100 for r in pairs]
    axs[1,0].scatter(a,b,color=COLORS[0],s=28)
    limit=max(a+b+[.1])*1.05
    axs[1,0].plot([0,limit],[0,limit],color='#666666',ls='--',lw=1)
    axs[1,0].set(xlim=(0,limit),ylim=(0,limit),xlabel='Flash单题猜（附加对照）：损失（%）',ylabel='日志＋逆优化＋稀疏：损失（%）',title='C  同题比较：虚线下方为本地方法更好')
    critical=[c for c in contrasts if c['right'] in ['no_text_sparse','text_no_l1']]
    for i,c in enumerate(critical):
        mean=c['meanDifference']*100;lo,hi=[x*100 for x in c['ci95']]
        axs[1,1].errorbar(mean,i,xerr=[[mean-lo],[hi-mean]],fmt='o',color=COLORS[i%len(COLORS)],capsize=4)
    axs[1,1].axvline(0,color='#666666',ls='--',lw=1)
    axs[1,1].set_yticks(range(len(critical)),['保留文本 − 去掉文本','加稀疏 − 不加稀疏'],fontsize=9)
    axs[1,1].set_ylim(-.6,1.6)
    axs[1,1].set(xlabel='平均损失差（百分点）及描述性 95% 区间',title='D  关键消融：区间跨零，额外收益不确定')
    fig.suptitle('MAMO 公开配餐题 · 遮蔽两项成本 · 独立测试场景\n主比较 K=10，训练近优差距上限10%；同题派生场景先平均，非真实人工日志',fontsize=13)
    fig.savefig(OUT/'实验总览.png',dpi=180);fig.savefig(OUT/'实验总览.pdf');plt.close(fig)


def report(summary,rows,problems):
    main=summary['primary']['methods']['text_sparse']['normalizedRegret']['mean']
    guess=summary['primary']['methods']['llm_guess']['normalizedRegret']['mean']
    improvement=(guess-main)/guess*100 if guess else None
    missing=summary['primary']['methods']['missing_text']['normalizedRegret']['mean']
    repaired=summary['primary']['methods']['local_feedback']['normalizedRegret']['mean']
    headline=f'固定遗漏对照：本地补漏把决策损失从 {missing*100:.2f}% 降到 {repaired*100:.2f}%'
    comparison='已有可重复的本地补漏效果；文本筛选和稀疏惩罚相对普通逆优化的额外收益尚不明确'
    table=''.join(f"<tr><td>{html.escape(LABELS[m])}</td><td>{v['completed']}/{v['attempted']}</td><td>{v['normalizedRegret']['mean']*100:.3f}%</td><td>{v['hiddenMAE']['mean']:.3f}</td><td>{v['cosine']['mean']:.3f}</td><td>{v['supportF1']['mean']:.3f}</td></tr>" for m,v in summary['primary']['methods'].items() if v['completed'])
    pairtable=''.join(f"<tr><td>{LABELS[c['left']]} − {LABELS[c['right']]}</td><td>{c['meanDifference']*100:.3f}</td><td>[{c['ci95'][0]*100:.3f}, {c['ci95'][1]*100:.3f}]</td><td>{c['wins']} / {c['ties']} / {c['losses']}</td></tr>" for c in summary['contrasts'])
    failed=summary['audit']['solverFailures']
    example=next(p for p in problems if p['id']==1)
    example_row=next(r for r in rows if r['id']==1 and r['K']==10 and r['noise']==.1 and r['method']=='text_sparse')
    example_truth=next(t for t in read(OUT/'oracle/truth.json') if t['id']==1)
    example_html='<h2>固定案例：第1题，看看它到底学到了什么</h2><p>案例按源数据编号固定选择，没有挑最好看的题。以下原始单价仅供结果核对，模型估计时看不到。</p><div class="panel"><ul>'+''.join('<li>'+html.escape(log)+'</li>' for log in example['logs'])+'</ul><div class="scroll"><table><thead><tr><th>候选规则</th><th>恢复的权重</th><th>实际隐藏权重</th></tr></thead><tbody>'
    if example_row['status']=='optimal':
        example_html+=''.join(f'<tr><td>{html.escape(f["label"])}</td><td>{example_row["theta"][j]:.4f}</td><td>{example_truth["truth"][j]:.4f}</td></tr>' for j,f in enumerate(example['bank']))
    example_html+='</tbody></table></div><p class="muted">数学含义：在已知采购成本上，加“未知单价 × 买入数量”；另三项衡量营养超出需求两成后的额外代价。权重为零表示本次拟合不保留该项，不证明所有真实业务中都不存在该规则。</p></div>'
    data=json.dumps([r for r in rows if r['split']=='evaluation'],ensure_ascii=False).replace('</','<\\/')
    text='''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>llm4orTT 0.1 · MAMO实验</title><style>
    :root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f5f3ee;color:#202b33;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1250px;margin:auto;padding:40px 28px}header{border-bottom:2px solid #254c4a;padding-bottom:24px}.eyebrow{letter-spacing:2px;font-size:12px;color:#506967}h1{font-size:32px;line-height:1.3;margin:12px 0}h2{font-size:22px;margin-top:38px}h3{font-size:17px}a{color:#006a82}p{max-width:1000px}.note{border-left:4px solid #b67938;padding:12px 18px;background:#fffaf0}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;padding:24px 0}.metric{border-top:1px solid #b9c3c0;padding-top:12px}.metric strong{display:block;font-size:32px;color:#17534e}.metric span{font-size:14px;color:#53635f}.panel{background:white;border:1px solid #d7ddd9;padding:22px;margin:18px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #e3e7e5;text-align:left;white-space:nowrap}th{color:#526763;background:#f4f6f5}img{width:100%;height:auto}select{padding:8px;margin:5px 16px 5px 0;border:1px solid #a3b5b0;background:white;border-radius:4px}button{padding:8px 14px;border:1px solid #17534e;color:#17534e;background:white;border-radius:4px;cursor:pointer}.barrow{display:grid;grid-template-columns:190px 1fr 120px;align-items:center;gap:12px;margin:14px 0;font-size:14px}.track{height:18px;background:#edf2f0}.bar{height:18px;background:#287b72;min-width:0}.muted{color:#5a686a;font-size:14px}li{margin:7px 0}footer{margin-top:35px;padding-top:16px;border-top:1px solid #bbc9c2;font-size:13px;color:#5a686a}@media(max-width:700px){main{padding:22px 14px}h1{font-size:25px}.metrics{grid-template-columns:repeat(2,1fr)}.barrow{grid-template-columns:130px 1fr 83px;font-size:12px;gap:6px}.panel{padding:12px}}
    </style></head><body><main><header><div class="eyebrow">llm4orTT 0.1 · RESEARCH MILESTONE · 2026-10-20</div><h1>公开题目上，先看历史，再还原成本</h1><p>HEADLINE。COMPARISON。固定批次已跑完，下面展示收益、没收益的消融和目前不能下的结论。</p></header>
    <div class="metrics"><div class="metric"><strong>39 / 40</strong><span>通过原题答案核对</span></div><div class="metric"><strong>31</strong><span>正式展示题目；另8题开发组</span></div><div class="metric"><strong>ROWS</strong><span>完成的实验条件记录</span></div><div class="metric"><strong>CALLS</strong><span>DeepSeek请求，后续可本地复算</span></div></div>
    <div class="note"><strong>这一版证明到哪里？</strong><br>使用已有公开 MAMO 题目；变化的需求、价格、历史决策和运营日志是受控生成的。结果只代表一个配餐问题家族，尚不能说已经达到 AAAI 录用水平，也不能当成真实工厂数据。排除的第23题存在原文歧义，未按方法表现挑题。</div>
    <h2>先看主比较</h2><p>每题使用10组训练历史，历史允许比最优方案贵至多10%；再考20个没见过的新场景。表内损失越低越好，余弦相似度和支持集F1越高越好。失效记录：FAILURES。</p><div class="panel scroll"><table><thead><tr><th>方法</th><th>成功/计划题数</th><th>新场景损失</th><th>两项成本MAE</th><th>权重余弦</th><th>目标项支持集F1</th></tr></thead><tbody>MAIN_TABLE</tbody></table></div>
    <p class="muted">支持集F1衡量候选目标项是否保留，不是一般隐式硬约束召回率。无文本方法使用5项受限候选字典，不是未知全矩阵逆优化。成本权重未必唯一；低决策损失不等于恢复了唯一真实权重。</p>
    <h2>样本少、历史有误差时怎样？</h2><div class="panel"><label>历史数量 <select id="k"><option value="5">5</option><option value="10" selected>10</option><option value="20">20</option></select></label><label>近优差距上限 <select id="noise"><option value="0">0%</option><option value="0.05">5%</option><option value="0.1" selected>10%</option><option value="0.15">15%</option></select></label><div id="bars"></div><p class="muted">条长表示新场景平均损失，起点为零；末尾标注实际成功/计划数。DeepSeek直接猜仅在主条件运行，切换条件时不借用其他条件的答案。</p></div>
    <h2>把每道题与不确定性一起摆出来</h2><figure><img src="实验总览.png" alt="主条件每题决策损失、K和噪声曲线、同题模型与求解器对比，以及题级配对区间"><figcaption class="muted">来源：固定 MAMO 配餐子集，2026-10-20。本批31道评估题，每题20个测试场景先平均。区间为题级5000次配对重采样的描述性95%区间，不代表跨行业的置信保证。</figcaption></figure>
    <div class="panel scroll"><table><thead><tr><th>配对比较：左减右</th><th>损失差（百分点）</th><th>描述性95%区间</th><th>左胜 / 平 / 负</th></tr></thead><tbody>PAIR_TABLE</tbody></table></div>
    <h2>这次到底做了什么</h2><ol><li>从作者官方Git固定提交下载数据，记录文件哈希和CC BY-SA许可证；39题整数模型的最优值与公开答案逐题一致。公开题部分没有明确写整数要求，因此同时存了连续松弛值，整数解释仍是一项建模限制。</li><li>每题遮蔽两个原有单价，保留其他已知成本作尺度锚。额外放入三项真实权重为零的营养超量惩罚，检验是否会保留无用规则。</li><li>日志只给出语义，不写隐藏数值；39题共5批DeepSeek请求提取候选。另8批请求完成31题的纯模型猜权重对照。缓存原始提示、回答、模型标识和用量。</li><li>本地HiGHS生成历史、构建次优性损失切平面、求解和测试。仅接受求解器证明最优的结果，失败单列。K使用同一训练前缀，所有方法看到相同历史。</li><li>固定9种本地方法 × 3档K × 4档噪声，未根据结果改样本量或调参。“本地补规则”只在训练集上从已有候选中补一项，不是发明任意新约束。</li></ol>
    <h2>下一步往AAAI靠，缺口已经清楚</h2><p>远期目标选 <a href="https://aaai.org/conference/aaai/aaai-27/areas-and-topics/">AAAI 主会的约束满足与优化方向</a>，对应 <a href="https://www.ccf.org.cn/Academic_Evaluation/AI/zgjsjxhtjgjxshy/al/">CCF人工智能A类目录</a>。AAAI-27主会截稿已过；准备后续开放届次，日期以官方新公告为准。</p><ul><li>扩展到运输、排班、设施选址等多个独立问题家族，并设置整类不参与开发的外部测试。</li><li>换成独立撰写且更含糊的日志，测文本抽取错误、遗漏与误导；当前模板透露目标项语义，不能证明一般自然语言理解能力。</li><li>补齐强逆优化基线、参数不可辨识分析和理论贡献；这批使用标准精确分离求解，本身不构成新算法证明。</li><li>保持当前固定结果为第一阶段证据；下一轮修改另开协议与目录，不能在本批测试题上反复调到好看。</li></ul>
    <h2>原始证据与复算</h2><p><a href="summary.json">汇总JSON</a> · <a href="all-results.json">逐条件原始结果</a> · <a href="source-audit.json">原题核对和排除记录</a> · <a href="protocol.json">固定实验协议</a> · <a href="audit.json">自动审计</a> · <a href="实验总览.pdf">可导出矢量图</a> · <a href="source-manifest.json">数据来源校验</a></p><button id="download">下载当前筛选结果JSON</button>
    <h2>依据的论文</h2><p><a href="https://arxiv.org/abs/2405.13144">MAMO：公开题目与求解器答案核对</a>；<a href="https://arxiv.org/abs/1512.05489">不完美信息下的数据驱动逆优化</a>；<a href="https://arxiv.org/abs/2405.14273">MILP逆优化中的次优性损失</a>。使用这些标准方法作基础，不把文献的一致性保证解释为“少量历史一定恢复唯一权重”。</p><footer>代码版本保持0.1.0。数据作者：Huang等；官方仓库 FreedomIntelligence/Mamo，固定提交 2c91069dee5c1e4db4b899eb176ec987d0251bb3。公开数据及其派生数据保留CC BY-SA 4.0归属与同许可说明。报告不含API密钥和私人聊天。</footer></main><script>
    const rows=DATA, labels=LABELS;let selected=[];
    function render(){const k=+document.querySelector('#k').value,n=+document.querySelector('#noise').value;selected=rows.filter(r=>r.K===k&&r.noise===n);const grouped=Object.keys(labels).map(method=>{const all=selected.filter(r=>r.method===method),good=all.filter(r=>r.status==='optimal');return {method,total:all.length,n:good.length,value:good.length?good.reduce((s,r)=>s+r.normalizedRegret,0)/good.length:null}}).filter(x=>x.total);const max=Math.max(.001,...grouped.map(r=>r.value||0));document.querySelector('#bars').innerHTML=grouped.map(r=>'<div class="barrow"><span>'+labels[r.method]+'</span><div class="track"><div class="bar" style="width:'+(r.value===null?0:100*r.value/max)+'%"></div></div><span>'+(r.value===null?'失败':(r.value*100).toFixed(2)+'%')+' ('+r.n+'/'+r.total+')</span></div>').join('')};document.querySelector('#k').addEventListener('change',render);document.querySelector('#noise').addEventListener('change',render);document.querySelector('#download').onclick=()=>{const u=URL.createObjectURL(new Blob([JSON.stringify(selected,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='mamo-selected-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};render();
    </script></body></html>'''
    text=text.replace('<h2>下一步往AAAI靠',example_html+'<h2>下一步往AAAI靠')
    text=text.replace('<h2>把每道题与不确定性一起摆出来</h2>','<p class="muted">噪声曲线并不单调；本批每题仅一个固定随机场景序列，不能据此声称加噪有益。下一轮需多随机种子及整类外部测试。</p><h2>把每道题与不确定性一起摆出来</h2>')
    sanity=read(OUT/'sanity-scores.json')
    caveat=f'<div class="note"><strong>别只看最大的提升。</strong>本方法主条件平均损失为{main*100:.2f}%，中位数为{summary["primary"]["methods"]["text_sparse"]["normalizedRegret"]["median"]*100:.2f}%，最差题仍高达{summary["primary"]["methods"]["text_sparse"]["normalizedRegret"]["max"]*100:.2f}%。相对无文本逆优化、相对不加稀疏惩罚的区间都跨过零，尚不能确认这两部分有额外收益。模型直接猜有许多0/20边界答案；额外3题单独提问时有{sanity["changed"]}题改变答案，说明批量提问影响结果。因此不能把相对这一弱对照的{improvement:.1f}%降幅当作击败强模型的证据。<a href="sanity-scores.json">查看单题核验</a>。</div>'
    text=text.replace('<h2>先看主比较</h2>',caveat+'<h2>先看主比较</h2>')
    text=text.replace('支持集F1衡量候选目标项是否保留，不是一般隐式硬约束召回率。', '支持集F1衡量候选目标项是否保留，不是一般隐式硬约束召回率。本批两项单价与三项附加惩罚在类型上可区分，固定中点基线也能获得完美支持集F1，不能拿这个指标宣称完成了困难的结构发现。')
    text=text.replace('<footer>', '<h2>执行记录</h2><p>首次v1在求解器接口遇到浮点极小系数警告，暂停并保留失败记录。v2仅修复数值接口，复用同一批数据、参数和13次模型回答，全部条件重算；这不是重新抽题。另有4项Pyomo与直接HiGHS建模的交叉核验通过。本轮模型是DeepSeek Flash非思考模式，不能代表全部大模型或更强推理配置。未验证网关计费单价，因此只报告实际请求与token用量，不虚构金额。</p><p>预测目标存在多个最优方案时，采用固定版本HiGHS返回的方案，没有用真实成本挑选对自己最有利的平局解。零权重可能造成严重不可辨识；主表只描述这一确定求解流程，尚未完成最坏平局或跨求解器敏感性测试。</p><p class="muted">实验设计、统计和绘图流程参考 Kassis、Agarwal、He、Patel 与 Brueckner（2026），<a href="https://doi.org/10.48550/arXiv.2609.00065">Scientific Agent Skills</a>；流程引用不代表对结果的背书。</p><footer>')
    for token,value in [('HEADLINE',headline),('COMPARISON',comparison),('ROWS',str(len(rows))),('CALLS',str(summary['spending']['calls'])),('FAILURES',str(failed)),('MAIN_TABLE',table),('PAIR_TABLE',pairtable),('DATA',data),('LABELS',json.dumps(LABELS,ensure_ascii=False))]:
        text=text.replace(token,value)
    (OUT/'实验报告.html').write_text(text,encoding='utf-8')
    single=summary['primary']['methods']['llm_single']['normalizedRegret']['mean']
    text=text.replace('另8批请求完成31题的纯模型猜权重对照。','另8批请求完成31题的纯模型猜权重对照；原阶段加3次诊断共16次。发现批量敏感后另立协议追加28次，复用3次，补齐全部31道单题对照；总计44次请求，均保留原记录。')
    text=text.replace('<h2>先看主比较</h2>',f'<p><strong>完整单题对照已补齐：</strong>同样31题的Flash单题猜平均损失为{single*100:.2f}%，本方法为{main*100:.2f}%。这一行和相应区间是发现批量问题之后追加的探索性核验，不能伪称预先注册结果。原批量对照仍列出，没有用新结果覆盖。</p><h2>先看主比较</h2>')
    (OUT/'实验报告.html').write_text(text,encoding='utf-8')
    (OUT/'先看这里.txt').write_text('llm4orTT 0.1 · MAMO 第一阶段实验\n'+headline+'\n'+comparison+f'\n补齐的Flash单题对照损失：{single*100:.2f}%；本方法：{main*100:.2f}%。\n39道公开题通过核对，31道评估，8道开发。原阶段16次、补全对照28次，总共44次DeepSeek请求。\n打开 实验报告.html 可看图、切换条件和查证据。\n这是公开基准派生实验，历史和日志受控生成，不是真实工厂记录；尚未达到顶会投稿完成状态。\n',encoding='utf-8')


def main():
    problems=read(OUT/'public/problems.json')
    rows=[r for p in sorted((OUT/'rows').glob('problem-*.json')) for r in read(p)['rows']]+read(OUT/'llm-guess-scores.json')+read(OUT/'llm-single-scores.json')
    checked=audit(rows,problems);save(OUT/'audit.json',checked)
    evalrows=[r for r in rows if r['split']=='evaluation']
    primary=[r for r in evalrows if r['K']==10 and r['noise']==.1]
    contrasts=[contrast(primary,a,b) for a,b in [('text_sparse','llm_guess'),('text_sparse','no_text_sparse'),
              ('text_sparse','text_no_l1'),('local_feedback','missing_text'),('text_sparse','shuffled_text')]]
    extra_contrast=contrast(primary,'text_sparse','llm_single');extra_contrast['phase']='exploratory after observed batch sensitivity';contrasts.append(extra_contrast)
    raw=[read(p) for folder in ['raw','single-raw'] for p in (OUT/'llm'/folder).glob('*.json')]
    usages=[r.get('usage') for r in raw];complete=all(u and u.get('prompt_tokens') is not None and u.get('completion_tokens') is not None for u in usages)
    spending={'calls':len(raw),'phase1Cap':16,'supplementCap':28,'usageComplete':complete,'inputTokens':sum((u or {}).get('prompt_tokens',0) for u in usages),
              'outputTokens':sum((u or {}).get('completion_tokens',0) for u in usages),'actualCurrencyCost':None,
              'reason':'Usage logged; gateway billing price not independently verified. No invented monetary saving.'}
    truths=read(OUT/'oracle/truth.json');evaluation={p['id'] for p in problems if p['split']=='evaluation'}
    noise={n:{'meanRealizedGap':statistics.mean(g for t in truths if t['id'] in evaluation for g in t['realizedGaps'][str(n)]),
              'nonOptimalFraction':statistics.mean(g>1e-8 for t in truths if t['id'] in evaluation for g in t['realizedGaps'][str(n)])} for n in [0,.05,.1,.15]}
    summary={'experiment':'mamo-diet-20261020-v2','evaluationProblems':len(evaluation),'developmentProblems':len(problems)-len(evaluation),
             'rows':len(rows),'audit':{'checkCount':checked['checkCount'],'solverFailures':checked['solverFailures']},
             'primary':{'K':10,'noise':.1,'methods':{m:stats([r for r in primary if r['method']==m]) for m in LABELS}},
             'contrasts':contrasts,'noise':noise,'spending':spending,
             'scope':'MAMO diet family, source-derived generated contexts and logs; descriptive exploratory result only'}
    diagnostics={}
    for method in LABELS:
        group=[r for r in primary if r['method']==method and r['status']=='optimal']
        vals=np.array([r['normalizedRegret'] for r in group]);q1,q3=np.quantile(vals,[.25,.75]);iqr=q3-q1
        diagnostics[method]={'n':len(group),'finite':bool(np.isfinite(vals).all()),'q1':float(q1),'q3':float(q3),
            'iqrOutlierIds':[r['id'] for r in group if r['normalizedRegret']<q1-1.5*iqr or r['normalizedRegret']>q3+1.5*iqr],
            'zeroWeightUnboundedTieRiskIds':[r['id'] for r in group if min(r['theta'][:2])<=1e-10 and max(r['theta'][2:])<=1e-10],
            'excludedOutliers':0}
    save(OUT/'distribution-diagnostics.json',{'unit':'one mean per source problem; one source family','normalityRequired':False,
        'notes':'Descriptive paired bootstrap; no normality test is used to select a favorable analysis. All extreme values retained. Zero-cost unbounded tie directions are a limitation of the chosen deterministic forward policy.', 'methods':diagnostics})
    save(OUT/'summary.json',summary);save(OUT/'all-results.json',rows)
    plot(evalrows,primary,contrasts);report(summary,rows,problems)
    save(OUT/'plot-environment.json',{'python':sys.version,'packages':{p:importlib.metadata.version(p) for p in ['matplotlib','numpy','pillow','pyparsing']},
        'figure':'14 x 10 inches, PNG180dpi and vector PDF; jitter deterministic; no discarded outliers'})
    print(json.dumps({'rows':len(rows),'mainRegret':summary['primary']['methods']['text_sparse']['normalizedRegret'],
          'guessRegret':summary['primary']['methods']['llm_guess']['normalizedRegret'],'contrasts':[{k:v for k,v in c.items() if k!='pairs'} for c in contrasts], 'spending':spending}),flush=True)


if __name__=='__main__':main()
