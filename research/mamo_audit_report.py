"""Render forensic evidence without changing any original benchmark score."""
import hashlib
import html
import importlib.metadata
import json
import os
import shutil
import statistics as st
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'outputs/inverse/mamo-diet-20261020-v2'
OUT=Path(os.environ.get('MAMO_AUDIT_OUT',str(ROOT/'outputs/inverse/mamo-audit-20261020-v1')))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'work/research/mplconfig'))
sys.path.insert(0,str(ROOT/'work/research/plot-deps'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def pct(v):return f'{100*v:.2f}%'
LABELS={'text_sparse':'文本＋逆优化＋稀疏','text_no_l1':'去掉稀疏','no_text_sparse':'去掉文本','no_text_no_l1':'文本稀疏都去掉',
 'midpoint':'固定报10（不学习）','zero_missing':'固定报0（不学习）','missing_text':'故意漏掉一项','local_feedback':'在漏项上本地补漏',
 'shuffled_text':'错置候选结构','llm_guess':'Flash批量直接猜','llm_single':'Flash单题直接猜（追加）'}
METHODS=['text_sparse','midpoint','text_no_l1','no_text_sparse','no_text_no_l1','missing_text','local_feedback','shuffled_text','zero_missing','llm_guess','llm_single']


def compile_evidence():
    d=read(OUT/'descriptive.json');profiles=[read(f) for f in (OUT/'profiles').glob('*.json')]
    profiles.sort(key=lambda r:r['id'])
    orders=[r for f in (OUT/'order').glob('*.json') for r in read(f)]
    d['orderSummary']={m:{'original':st.mean(r['originalRegret'] for r in orders if r['method']==m),
                         'reversed':st.mean(r['reversedRegret'] for r in orders if r['method']==m),
                         'changed':sum(abs(r['originalRegret']-r['reversedRegret'])>1e-8 for r in orders if r['method']==m)} for m in METHODS}
    d['profiles']=profiles;d['orders']=orders
    d['solverSensitivity']=read(OUT/'solver-sensitivity.json');d['historySensitivity']=read(OUT/'history-sensitivity.json')
    d['ties']=read(OUT/'tie-certificates.json');d['verification']=read(OUT/'verification.json')
    d['trueOutsideProfileCount']=sum(v['truth']<v['lower']['bound']-1e-6 or v['truth']>v['upper']['bound']+1e-6 for p in profiles for v in p['parameters'])
    primary=[r for r in read(OLD/'all-results.json') if r['split']=='evaluation' and r['K']==10 and r['noise']==.1]
    details=[]
    problems={p['id']:p for p in read(OLD/'public/problems.json')}
    truth={p['id']:p for p in read(OLD/'oracle/truth.json')}
    for act in d['activation']:
        pid=act['id'];p=problems[pid];t=truth[pid];noises=[]
        for cap in ['0.1','0.15']:
            samples=p['histories'][cap][:10]
            noises.append({'noise':float(cap),'knownActiveContexts':[s['id'] for s in samples if np.dot(s['base'],s['decision'])>1e-8],
                 'actualMeanGap':st.mean(t['realizedGaps'][cap][:10]),
                 'theta':next(v['theta'] for v in read(OLD/f'rows/problem-{pid}.json')['rows'] if v['K']==10 and v['noise']==float(cap) and v['method']=='text_sparse')})
        details.append({**act,'rows':[r for r in primary if r['id']==pid],'profiles':next(v for v in profiles if v['id']==pid),
                        'noiseDetails':noises,'orders':[r for r in orders if r['id']==pid]})
    d['details']=details
    d['claims']=[
      {'claim':'文本先验提供额外收益','status':'尚未证实；撤回肯定性卖点','reason':'平均差−0.361百分点，95%描述性区间[−0.954,+0.125]跨零；22/31题打平。','evidence':'descriptive.json → contrasts/no_text_sparse'},
      {'claim':'稀疏正则提供额外收益','status':'尚未证实；撤回肯定性卖点','reason':'平均差−0.191百分点，区间[−0.887,+0.521]跨零；24/31题打平。零向量退化时惩罚反而偏向全零。','evidence':'descriptive.json → contrasts/text_no_l1'},
      {'claim':'比不学习、固定报10更好','status':'尚未证实','reason':'37.19%对41.43%；配对差−4.24百分点，区间[−39.22,+44.16]跨零，16胜2平13负。','evidence':'descriptive.json → contrasts/midpoint'},
      {'claim':'噪声越大效果越好','status':'撤回这种解读','reason':'两题贡献下降32.10百分点，其余29题合计反而抵消0.83百分点；噪声生成换了决策内容。','evidence':'descriptive.json → noise; history-sensitivity.json'},
      {'claim':'赢过这次Flash直接猜配置','status':'保留原条件下的有限描述','reason':'原始平均37.19%低于333.30%/466.76%；两个配置大多报边界值，不能外推为战胜强大模型或通用纯LLM基线。','evidence':'descriptive.json → llm; order/*'},
      {'claim':'在固定漏项对照上补漏降低损失','status':'有条件保留','reason':'300.99%到37.49%，配对区间支持此批差异；但人为删去一个真实成本，封闭候选库枚举，不能叫开放隐式约束发现。','evidence':'descriptive.json → contrasts/missing_text'},
      {'claim':'少量历史已恢复真实价格与隐式结构','status':'不成立；撤回广泛表述','reason':'25/62价格从未被历史激活；62个经验最优范围中32个不含真值。F1中固定报10已等于1，不是一般结构发现证据。','evidence':'profiles/*; inactive-unbounded-price-witnesses.json'},
      {'claim':'求解与数据流程可复算','status':'保留','reason':'原始4274条完整；全部341条主比较重新求解核对，原封存文件不变；求解最优不代表科学结论成立。','evidence':'verification.json; original-seal.json'}]
    save(OUT/'audit-summary.json',d);save(OUT/'claims-ledger.json',d['claims'])
    return d,primary


def figure_save(fig,name):
    fig.savefig(OUT/(name+'.png'),dpi=180);fig.savefig(OUT/(name+'.pdf'));plt.close(fig)


def figures(d,primary):
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
                        'font.size':10,'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
    fig,axs=plt.subplots(2,1,figsize=(12,11),layout='constrained')
    for panel,ax in enumerate(axs):
        for i,m in enumerate(METHODS):
            rr=sorted([r for r in primary if r['method']==m],key=lambda r:r['id'])
            vals=np.array([r['normalizedRegret']*100 for r in rr]);jitter=np.linspace(-.2,.2,31)
            ax.scatter(vals,i+jitter,s=15,color='#0072B2',alpha=.65,label='31题原始点' if i==0 else None)
            ax.scatter([vals.mean()],[i],marker='D',s=44,color='#222222',label='原始均值' if i==0 else None)
            ax.scatter([np.median(vals)],[i],marker='|',s=180,color='#D55E00',label='中位数' if i==0 else None)
        ax.set_yticks(range(len(METHODS)),[LABELS[m] for m in METHODS]);ax.invert_yaxis();ax.grid(axis='x',alpha=.2)
        ax.set_xlabel('原口径：测试决策额外成本（%）；没有删题或改分母')
        if panel==0:
            ax.set_xlim(left=-20);ax.set_title('A  原始线性全范围：保留全部341个点，离群值确实挤压了主体');ax.legend(loc='lower right',fontsize=9)
        else:
            ax.set_xscale('symlog',linthresh=1,base=10);ax.set_xlim(left=-.05)
            ax.set_xticks([0,1,10,100,1000],['0','1','10','100','1,000'])
            ax.set_xlim(right=max(r['normalizedRegret']*100 for r in primary)*1.15)
            ax.set_title('B  同一批点换显示刻度：0–1%线性，1%以上以10为底对数；零值照留')
    fig.suptitle('原始成绩不改，只修复展示盲点\nMAMO配餐31题 · K=10 · 历史近优差距上限10% · 固定报10/0均已纳入',fontsize=13)
    figure_save(fig,'01_原始成绩全量展示')
    fig,axs=plt.subplots(2,2,figsize=(13,9),layout='constrained')
    r=d['methods']['text_sparse'];ranked=r['ranked'];ax=axs[0,0]
    ax.bar(['39号','2号','其余29题'],[100*ranked[0]['regret']/31,100*ranked[1]['regret']/31,100*sum(v['regret'] for v in ranked[2:])/31],color=['#D55E00','#E69F00','#0072B2'])
    ax.set(ylabel='对31题均值的贡献（百分点）',title='A  两题占总损失86.50%；原均值仍为37.19%')
    ax=axs[0,1]
    allrows=read(OLD/'all-results.json')
    for k,marker in zip([5,10,20],['o','s','^']):
        values=[100*st.mean(r['normalizedRegret'] for r in allrows if r['split']=='evaluation' and r['method']=='text_sparse' and r['K']==k and r['noise']==n) for n in [0,.05,.1,.15]]
        ax.plot([0,5,10,15],values,marker=marker,label=f'K={k}')
    ax.set(xlabel='历史近优差距上限（%，非污染比例）',ylabel='原口径平均额外成本（%）',title='B  保留原噪声曲线，不解释成噪声越大越好');ax.set_xticks([0,5,10,15]);ax.legend()
    jump=next(v for v in d['noise'] if v['K']==10 and v['low']==.1)
    ax=axs[1,0];vv=[next(v['contributionToMean']*100 for v in jump['pairs'] if v['id']==i) for i in [39,2]]
    vv.append((jump['highMean']-jump['lowMean'])*100-sum(vv));ax.bar(['39号','2号','其余29题'],vv,color=['#D55E00','#E69F00','#0072B2']);ax.axhline(0,color='#333',lw=.8)
    for i,v in enumerate(vv):ax.text(i,v+(.5 if v>=0 else -.5),f'{v:+.2f}',ha='center',va='bottom' if v>=0 else 'top')
    ax.set_ylim(-32,5);ax.set(ylabel='均值变化贡献（百分点）',title='C  K=10：10%→15%的突降由哪题造成')
    ax=axs[1,1]
    for i,pid in enumerate([2,39]):
        for cap,offset,marker,color in [(.1,-.1,'o','#0072B2'),(.15,.1,'s','#D55E00')]:
            h=[v for v in d['historySensitivity'] if v['id']==pid and v['noise']==cap]
            ax.scatter(i+offset+np.linspace(-.045,.045,len(h)),[v['normalizedRegret']*100 for v in h],marker=marker,color=color,label=f'上限{cap*100:.0f}%' if i==0 else None)
    ax.set_xticks([0,1],['2号','39号']);ax.set(xlim=(-.5,1.5),ylabel='原测试集平均额外成本（%）',title='D  换5组历史随机种子：15%时仍可崩塌');ax.legend(loc='upper left')
    fig.suptitle('归因诊断：异常点、噪声换样和零价格退化\n补充实验仅改变历史噪声抽样；原训练场景、原测试场景和原计分公式均保留',fontsize=13)
    figure_save(fig,'02_异常与噪声归因')
    fig,axs=plt.subplots(3,1,figsize=(11,6),layout='constrained')
    for ax,m,title in zip(axs,['no_text_sparse','text_no_l1','midpoint'],['文本的额外收益','稀疏的额外收益','相对固定报10的收益']):
        c=next(v for v in d['contrasts'] if v['right']==m);mean=c['meanDifference']*100;lo,hi=[v*100 for v in c['ci95']]
        ax.errorbar(mean,0,xerr=[[mean-lo],[hi-mean]],fmt='o',color='#0072B2',capsize=6);ax.axvline(0,color='#333',ls='--');ax.set_yticks([])
        ax.set_title(f'{title}：{mean:+.3f}，95%区间[{lo:+.3f}, {hi:+.3f}]；{c["wins"]}胜/{c["ties"]}平/{c["losses"]}负')
        ax.set_xlabel('本方法 − 对照：额外成本差（百分点）；负值有利于本方法')
    fig.suptitle('三项差异均跨零：不支持肯定性收益卖点\n31道同家族源题配对bootstrap，5000次，种子20261020；描述性未校正95%区间，各面板横轴范围不同',fontsize=12)
    figure_save(fig,'03_不能宣称的收益')
    fig,axs=plt.subplots(1,2,figsize=(12,12),layout='constrained',sharey=True)
    act={r['id']:r for r in d['activation']}
    for j,ax in enumerate(axs):
        for i,p in enumerate(d['profiles']):
            v=p['parameters'][j];unused=act[p['id']]['hidden'][j]['positiveHistories']==0;col='#D55E00' if unused else '#0072B2'
            ax.plot([v['lower']['bound'],v['upper']['bound']],[i,i],color=col,lw=2,ls='--' if unused else '-')
            ax.scatter([v['lower']['bound'],v['upper']['bound']],[i,i],color=col,s=12)
            ax.scatter(v['truth'],i,marker='x',color='#222222',s=24)
        ax.set_title(f'第{j+1}个隐藏单价');ax.set_xlabel('经验近最小损失可行范围；人为搜索框[0,20]');ax.set_xlim(-.5,20.7);ax.set_xticks([0,5,10,15,20]);ax.grid(axis='x',alpha=.2)
    axs[0].set_yticks(range(31),[str(p['id']) for p in d['profiles']]);axs[0].invert_yaxis();axs[0].set_ylabel('原始题号（无删题）')
    from matplotlib.lines import Line2D
    axs[0].legend(handles=[Line2D([0],[0],color='#D55E00',ls='--',label='历史从未选用'),Line2D([0],[0],color='#0072B2',label='历史至少选过一次'),Line2D([0],[0],marker='x',color='#222',ls='',label='真实价格（仅核对）')],loc='lower right',fontsize=8)
    fig.suptitle('17/31题存在未选过的隐藏食材，共25/62个价格没有数据给出的有限上界\n这些线是经验拟合范围，不是置信区间；32/62个范围不含真实价格，窄也不代表学对',fontsize=12)
    figure_save(fig,'04_逐题价格可辨识性')


def report(d,primary):
    def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    methodtable=table(['方法','原始均值','中位数','超过100%题数','前两题占总损失','只反转排列后均值（诊断）'],[[LABELS[m],pct(d['methods'][m]['mean']),pct(d['methods'][m]['median']),len(d['methods'][m]['catastropheIds']),pct(d['methods'][m]['top2Share']),pct(d['orderSummary'][m]['reversed'])] for m in METHODS])
    contrasts=table(['比较（本方法减对照）','平均差/百分点','描述性95%区间','胜/平/负'],[[LABELS[c['left']]+' − '+LABELS[c['right']],f'{c["meanDifference"]*100:+.3f}',f'[{c["ci95"][0]*100:+.3f}, {c["ci95"][1]*100:+.3f}]',f'{c["wins"]}/{c["ties"]}/{c["losses"]}'] for c in d['contrasts']])
    ledger=table(['原说法或容易形成的解读','处置','理由','复核入口'],[[c['claim'],c['status'],c['reason'],c['evidence']] for c in d['claims']])
    solver=table(['题/方法','原排列','反转排列','5个种子是否改变该排列的结果'],[[str(r['id'])+' / '+LABELS[r['method']],pct(r['originalRegret']),pct(next(v['meanRegret'] for v in r['variants'] if v['reverseOrder'])),'没有'] for r in d['solverSensitivity']])
    history=table(['题号','近优上限','5个补充种子的测试多花费（%）','崩塌次数（>100%）'],[[pid,f'{cap*100:.0f}%', ' / '.join(f'{r["normalizedRegret"]*100:.3f}' for r in d['historySensitivity'] if r['id']==pid and r['noise']==cap),sum(r['normalizedRegret']>1 for r in d['historySensitivity'] if r['id']==pid and r['noise']==cap)] for pid in [2,39] for cap in [.1,.15]])
    profiles=table(['题号','隐藏食材','历史使用次数/10','真实价格','经验可行下界','经验可行上界','解释'],[[p['id'],html.escape(next(a for a in d['activation'] if a['id']==p['id'])['hidden'][v['feature']]['name']),next(a for a in d['activation'] if a['id']==p['id'])['hidden'][v['feature']]['positiveHistories'],v['truth'],f'{v["lower"]["bound"]:.5f}',f'{v["upper"]["bound"]:.5f}','20是人为上限，历史无有限上界' if v['upper']['bound']>19.99999 else '经验范围不是价格置信区间'] for p in d['profiles'] for v in p['parameters']])
    htmltext='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>llm4orTT 0.1 · MAMO查账修正版</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f7f6f2;color:#202c33;font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1200px;margin:auto;padding:35px 26px}header{border-bottom:2px solid #234c51;padding-bottom:22px}h1{font-size:30px;line-height:1.35}h2{font-size:23px;margin-top:38px}h3{font-size:18px}a{color:#006a82}p{max-width:1020px}.tag{font-size:13px;letter-spacing:1px;color:#546267}.notice{border-left:4px solid #a34e22;background:#fff5e7;padding:13px 20px;margin:20px 0}.fact{font-size:19px}.muted,figcaption{color:#53606a;font-size:14px}nav{display:flex;flex-wrap:wrap;gap:18px;margin:20px 0}.scroll{overflow:auto;max-width:100%}table{width:100%;border-collapse:collapse;background:white;font-size:14px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #ddd;vertical-align:top}th{background:#edf1ef;white-space:nowrap}td{min-width:85px}img{display:block;width:100%;height:auto}figure{margin:24px 0}details{margin:18px 0;border-top:1px solid #cad3d0;padding-top:12px}summary{cursor:pointer;font-weight:600}select,button{font:inherit;padding:6px 12px;border:1px solid #78908c;background:white;color:#203d3a}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef1ed;padding:16px;font-size:13px}code{overflow-wrap:anywhere}li{margin:8px 0}.detail{border-left:3px solid #23746a;padding-left:15px}footer{margin-top:35px;border-top:1px solid #bac6c0;padding-top:20px;font-size:13px}@media(max-width:650px){main{padding:20px 13px}h1{font-size:24px}h2{font-size:20px}.notice{padding:12px}td{min-width:100px}}
    </style></head><body><main><header><div class="tag">llm4orTT 0.1 · 2026-10-20 · 事后审计 / 旧账不改</div><h1>这张图的毛病，已经逐题查清</h1><p class="fact">七个疑点都值得查。真正的问题，是<strong>价格学不准、零价格造成同样最优解、少数题主导均值，以及对照和结论展示不完整</strong>。不是把图画漂亮就能解决。</p><p>保留原始4274条成绩；主比较仍是31题、每题原来的20个测试场景、K=10、近优差距上限10%。新增内容均标明“事后诊断”，没有删测试题、换分母或替换失败分数。此次新增付费模型调用：0。</p></header>
    <nav><a href="#seven">七项答复</a><a href="#all">全部成绩</a><a href="#case">逐题查账</a><a href="#claims">结论去留</a><a href="#replay">复算与旧账</a></nav>
    <div class="notice"><strong>先认账：</strong>文本和稀疏的额外收益都没有证实；相对固定报10的优势也没有证实。将这些写成已经成立的卖点应收回。原始成绩可以复现，但不能据此宣称真实价格恢复、一般隐式约束发现或顶会级证据已经齐备。</div>
    <section id="seven"><h2>一、几棵坏苗把图撑满了吗？——是，但不能只怪坏苗</h2>
    <p>本方法原均值<strong>37.19%</strong>、中位数<strong>2.81%</strong>；39号题<strong>861.81%</strong>、2号题<strong>135.49%</strong>，分别占总损失74.75%和11.75%，合计<strong>86.50%</strong>。只作影响诊断，去掉39号后的均值是9.70%，再去掉2号是5.37%；这两个数<strong>不能替代正式37.19%</strong>。</p>
    <p>直接猜的高线也不是一两个点的全部责任：批量猜前两题占METHOD_BATCH_TOP2，单题猜前两题占METHOD_SINGLE_TOP2；超过100%的题数分别为METHOD_BATCH_BAD和METHOD_SINGLE_BAD。下面既保留全范围图，也用明确标注的对数显示让主体可见。根子一半在算法退化，一半在只看均值的展示。</p>
    <h2>二、几十倍的崩塌，是偶然还是有准头？——原条件稳定，换表示或历史会变</h2>
    <p>2号、39号在主条件下的10条历史，全部只买了隐藏价格食材，已知成本支出都为0。若未知价格和惩罚也填0，历史残差就为0；L1又偏爱小权重，所以全零是这个目标下的最优解。去掉L1也不能凭空补足信息，不能全怪稀疏。</p>
    SOLVER_TABLE
    <p>固定数学问题和测试场景，只反转变量、约束顺序就明显改变真实成本，说明<strong>最优方案不唯一，默认取哪一个影响结论</strong>。并非求解器没找到所给模型的最优解。已对全部31题×11方法重算两种排列；这里只展示最明显的四例，全部结果见下表及order文件。</p>
    <p><strong>可手算的证据：</strong>39号的p39-c20场景，原解买28份鸡胸肉，真实成本112；另一最优解买17份菠菜，真实成本17。估计价格全0时，两者估计成本都等于0。还可以不断增加鸡胸肉，估计成本仍为0，真实成本却一直涨；因此最坏同价解损失没有有限上界。2号同样成立。保存了98个“方法—题目”射线证书，并非只看两次求解猜原因。</p>
    <p>额外用5组种子重抽2号、39号的历史决策，训练场景和测试集都没换。补充种子为101、202、303、404、505：HISTORY_TABLE</p>
    <p class="muted">这是选定异常题的敏感性诊断，不是总体故障率估计，也不是新的正式成绩。没有凭反转排列得到的低损失替换原成绩。</p>
    <h2>三、噪声越大，线反而往下掉？——两题换了历史信息，不是噪声有益</h2>
    <p>K=10时，原均值从37.19%降到5.92%。39号贡献<strong>−27.73个百分点</strong>，2号贡献<strong>−4.37个百分点</strong>；其余29题合计<strong>+0.83个百分点</strong>，反而抵消了一点改善。这两题解释了总降幅的102.65%。</p>
    <p>10%上限时两题都没有已知价格食材出场；15%时2号的c3、c4、c6出现了，39号的c6、c7出现了。新的买菜记录给价格提供了比较依据，打破全零解。原协议每个噪声档还换了独立随机方向，所以这不是把同一记录“逐渐加脏”的单因素因果试验。补充复算中，15%仍各有1/5次崩塌，不能说更大噪声保证更好。</p>
    <h2>四、两个卖点的区间跨零？——你没看错，额外收益未证实</h2>
    <p>文本的平均差是−0.361个百分点，区间[−0.954,+0.125]；稀疏是−0.191，区间[−0.887,+0.521]。分别有22题、24题打平。<strong>应撤回“已经证明有收益”的说法</strong>，但“没有证明有用”也不等于“已经证明永远无用”。所有区间按31道源题配对重抽，不能把同题20个派生场景当成独立620题，也不作跨任务家族推断。</p>
    <h2>五、直接猜只报0和顶格？——弱对照是真问题</h2>
    <p>两项隐藏价格共62个输出，批量猜有<strong>54/62（87.10%）</strong>落在0或20；单题猜有<strong>59/62（95.16%）</strong>。批量有12题全零，单题有10题全零。换成单题请求后，CHANGED_LLM/31题的权重发生变化，均值反而更差，不能只挑三题改善的诊断来讲故事。</p>
    <p>赢过这两种具体Flash配置的原始事实保留；不能把它升级成“胜过大模型推理”或“证明文本+稀疏创新”。同一个零价格陷阱对我们和对照一视同仁，都已检查。未追加更强模型付费调用，也不假装完成了强LLM基线。</p>
    <h2>六、啥也不学、直接报数的对照？——做过，图漏了；优势并不稳</h2>
    <p>旧数据里已有固定[10,10,0,0,0]及全零两组。固定报10的均值<strong>41.43%</strong>，我们<strong>37.19%</strong>；逐题16胜、2平、13负，配对平均差<strong>−4.24个百分点</strong>，区间<strong>[−39.22,+44.16]</strong>跨零。目前不能确认学历史优于这个固定数字策略。没有在测试集上挑一个最利于我们的常数；沿用原来那组10。</p>
    <h2>七、没种过的菜价能学出来吗？——17题、25个价格没有有限上界</h2>
    <p>主条件下有<strong>17/31题</strong>至少一种隐藏食材从未被买过，共<strong>25/62个隐藏单价</strong>。题号为1、3、6、8、9、11、14、16、18、24、27、28、29、32、33、36、38。这不同于2号、39号：后两题隐藏食材有使用，但已知价格的食材没有使用，缺少比较锚点。</p>
    <p>比如1号第一个价格，历史使用0次，真实8；接近最小训练损失的范围为[2.33541,20]。8号两种都没用，范围分别[2.21032,20]、[1.21516,20]，真实5和9。把所有25个未用价格分别提高到100，仍保持同样好拟合。20仅是我们给程序的搜索上限，不是历史算出的上限。</p>
    <p>道理是：没买过的菜涨价，不会改变历史采购账单，只会让别的买法更不划算。因此它可能给出“不应太便宜”的下界，却不能确定实际价格。<strong>见过也不等于学准</strong>：62个经验最优范围中32个不含真值。范围是原损失最小值附近的解集，不是统计置信区间；有噪声和目标偏差时，范围很窄也可能错得很稳。</p></section>
    <section id="all"><h2>正式成绩原封不动，诊断另列</h2>METHOD_TABLE
    <p class="muted">“反转排列”列只检验表示敏感性，不参加原始排名。每种方法都用完全相同的测试集。坏解没有从均值中删掉；全部341条主比较在原排列下已重新求解复现。</p>
    <figure><img src="01_原始成绩全量展示.png" alt="11种方法全部31题的原始点、均值及中位数；上下分别线性和明确标注的对数显示"><figcaption>同一份原始数值的两种显示。蓝点是每题平均多花费，黑菱形均值、橙竖线中位数。<a href="01_原始成绩全量展示.pdf">矢量PDF</a></figcaption></figure>
    <figure><img src="02_异常与噪声归因.png" alt="两题贡献86.5%的总损失；噪声下降分解及20次额外历史抽样复算"><figcaption>原曲线保留。贡献分解相加精确等于均值变化；补充随机种子不改变测试集。<a href="02_异常与噪声归因.pdf">矢量PDF</a></figcaption></figure>
    CONTRAST_TABLE
    <figure><img src="03_不能宣称的收益.png" alt="文本、稀疏和相对固定报10三项配对平均差的描述性95%区间都跨零"><figcaption>同题配对bootstrap 5000次、种子20261020；未做多重比较校正，均为同家族描述性区间。第三行尺度更大，面板各自标尺已明示。<a href="03_不能宣称的收益.pdf">矢量PDF</a></figcaption></figure>
    <figure><img src="04_逐题价格可辨识性.png" alt="31题两个隐藏价格的经验拟合范围，标记从未选过的25项和真实价格"><figcaption>固定原文本候选[0,1,2]，去掉L1，计算训练损失最小值+10⁻⁶内每个价格的上下界；精确MILP分离、LP最优求解及124个端点证据。不是置信区间。<a href="04_逐题价格可辨识性.pdf">矢量PDF</a></figcaption></figure>
    <details><summary>展开全部62个价格的上下界与历史使用次数</summary>PROFILE_TABLE</details></section>
    <section id="case"><h2>逐题账本：每一块地都能点开</h2><label for="problem">选择原题号：</label><select id="problem">OPTIONS</select> <button id="download">下载本题证据JSON</button><div id="detail" class="detail"></div><p class="muted">固定主条件K=10、近优上限10%；两档噪声和两种排列单独列出。训练历史与测试决策从不混为一谈。</p></section>
    <section id="claims"><h2>哪些话保留，哪些收回</h2>LEDGER
    <h3>修了什么，没有偷改什么</h3><p>修复的是证据链和报告：补齐固定常数对照、离群值影响、默认最优解选择敏感性、逐题可辨识性、批量/单题LLM对照局限，并把肯定性卖点改为未证实。没有在这批已看过的测试题上加价格下限、改L1系数、删困难题、挑求解器排列或挑随机种子去“抢救”分数。</p>
    <p>下一版算法的科学门槛应是：事先确定正价格/尺度锚定规则、独立于真值的最优解选取规则和不确定性输出；只在开发集选择这些规则，再冻结后评价。对没有价格信息的题，应明确输出“不可确定”，不能把某个任意最优点包装成恢复成功。这是后续研究工作，此报告没有把待验证的修法冒充完成的改进。</p></section>
    <section id="replay"><h2>复算、原始数据与保留的旧账</h2>
    <p>核验检查CHECK_COUNT项全部通过；原封存OLD_COUNT个文件哈希不变。数据来自固定版本MAMO公开配餐题；原审计40题中39题匹配公布整数答案，23号因原题营养要求歧义预先排除，8题开发、31题评价。这里只覆盖一个任务家族；运营日志、上下文及历史决策由程序生成，不是真实工人记录。原题公布最优值匹配不证明建模语义完全等价。</p>
    REPLAY_NOTE
    <ul><li><a href="原始实验_v2/实验报告.html">旧报告原件</a> · <a href="original-seal.json">修改前SHA256封存清单</a> · <a href="原始实验_v2/all-results.json">原始4274条结果</a></li>
    <li><a href="audit-protocol.json">事后审计协议</a> · <a href="order-protocol-addendum.json">全量排列核验补充协议</a> · <a href="audit-summary.json">完整审计数据</a></li>
    <li><a href="tie-certificates.json">98个同价最优解无界证书</a> · <a href="inactive-unbounded-price-witnesses.json">25个价格提高到100的证据</a> · <a href="history-sensitivity.json">20次补充历史复算</a></li>
    <li><a href="claims-ledger.json">结论处置账本</a> · <a href="verification.json">逐项计算核验</a> · <a href="复算说明.txt">复算命令与文件说明</a> · <a href="evidence-manifest.json">本次交付文件校验清单</a></li></ul>
    <p class="muted">审计目标是解释已有结果，不是一次新的预注册优越性试验。统计区间不能跨任务家族泛化；新增随机种子只用于两道异常题，不拿来估计31题总体故障概率。</p></section>
    <footer>llm4orTT 0.1.0 · 原数据、原测试地、原记账办法不改 · 新证据另立账本 · 付费API新增调用0次</footer></main><script>
    const DATA=DATA_JSON,LABELS=LABEL_JSON;
    const pct=v=>(100*v).toFixed(3)+'%';
    function draw(){const p=DATA.find(p=>p.id===Number(document.getElementById('problem').value));
    const wrap=document.getElementById('detail');wrap.replaceChildren();
    const add=(tag,text)=>{const x=document.createElement(tag);x.textContent=text;wrap.append(x);return x};
    add('h3','原始题号 '+p.id);add('p','已知价格食材在10条历史中出现 '+p.knownCostActiveHistories+' 次；原训练归一化尺度 '+p.scale.toFixed(5));
    p.hidden.forEach((h,j)=>{const v=p.profiles.parameters[j];add('p',h.name+'：历史使用 '+h.positiveHistories+'/10 次，总数量 '+h.totalQuantity+'；真实单价 '+h.truth+'；经验范围 ['+v.lower.bound.toFixed(5)+', '+v.upper.bound.toFixed(5)+']；原测试真值最优方案使用 '+h.testOraclePositiveContexts+'/20 次（只用于审计）。')});
    add('h3','原始成绩与排列诊断');p.rows.forEach(r=>{const o=p.orders.find(o=>o.method===r.method);add('p',LABELS[r.method]+'：原 '+pct(r.normalizedRegret)+'；反转排列 '+pct(o.reversedRegret)+'；权重 ['+r.theta.map(v=>v.toFixed(4)).join(', ')+']')});
    add('h3','噪声两档的历史信息');p.noiseDetails.forEach(n=>add('p','上限 '+pct(n.noise)+'；实际平均近优差距 '+pct(n.actualMeanGap)+'；已知成本食材出场于 '+(n.knownActiveContexts.join(', ')||'无')+'；估计权重 ['+n.theta.map(v=>v.toFixed(4)).join(', ')+']'));
    const link=add('a','本题上下界求解证据');link.href='profiles/problem-'+p.id+'.json';}
    document.getElementById('problem').addEventListener('change',draw);
    document.getElementById('download').addEventListener('click',()=>{const p=DATA.find(p=>p.id===Number(document.getElementById('problem').value));const url=URL.createObjectURL(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='audit-problem-'+p.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});draw();
    </script></body></html>'''
    replacements={'METHOD_BATCH_TOP2':pct(d['methods']['llm_guess']['top2Share']),'METHOD_SINGLE_TOP2':pct(d['methods']['llm_single']['top2Share']),
        'METHOD_BATCH_BAD':str(len(d['methods']['llm_guess']['catastropheIds'])),'METHOD_SINGLE_BAD':str(len(d['methods']['llm_single']['catastropheIds'])),
        'CHANGED_LLM':str(len(d['llm']['changedIds'])),'SOLVER_TABLE':solver,'HISTORY_TABLE':history,'METHOD_TABLE':methodtable,
        'CONTRAST_TABLE':contrasts,'PROFILE_TABLE':profiles,'LEDGER':ledger,'OPTIONS':''.join(f'<option value="{p["id"]}"'+(' selected' if p['id']==39 else '')+f'>{p["id"]}</option>' for p in d['details']),
        'CHECK_COUNT':str(d['verification']['count']),'OLD_COUNT':str(d['verification']['originalFilesUnchanged']),
        'REPLAY_NOTE':('<p><strong>已在全新目录从零重算：</strong>67份数值证据文件完全一致，另一次1972项检查全部通过；没有复用拟合与诊断检查点。<a href="fresh-recompute-verification.json">查看从零重算核验</a></p>' if (OUT/'fresh-recompute-verification.json').exists() else ''),
        'DATA_JSON':json.dumps(d['details'],ensure_ascii=False).replace('</','<\\/'),'LABEL_JSON':json.dumps(LABELS,ensure_ascii=False)}
    for k,v in replacements.items():htmltext=htmltext.replace(k,v)
    (OUT/'审计报告.html').write_text(htmltext,encoding='utf8')


def package():
    archived=OUT/'原始实验_v2'
    if not archived.exists():shutil.copytree(OLD,archived)
    for name,digest in read(OUT/'original-seal.json')['files'].items():
        if hashlib.sha256((archived/name).read_bytes()).hexdigest()!=digest:raise ValueError('Archived original mismatch: '+name)
    code=OUT/'复现源码';code.mkdir(exist_ok=True)
    for name in ['mamo_audit.py','mamo_audit_verify.py','mamo_audit_report.py','mamo_experiment.py']:
        shutil.copyfile(ROOT/'research'/name,code/name)
    scripts=code/'scripts';scripts.mkdir(exist_ok=True)
    for name in ['mamo-audit.mjs','mamo-audit-qa.mjs']:
        shutil.copyfile(ROOT/'scripts'/name,scripts/name)
    (OUT/'复算说明.txt').write_text('''llm4orTT 0.1 — MAMO事后审计复算

1. 原始实验_v2保留旧报告、4274条原始成绩、训练/测试场景与所有API原始结果。
   original-seal.json保存修改前SHA256；审计从不修改原文件。
2. 在项目根目录 D:\\scr\\llm4orOvO 工程 使用以下本地命令（不请求模型）：
   .\\runtime\\python\\python.exe -X utf8 research/mamo_audit.py describe
   .\\runtime\\python\\python.exe -X utf8 research/mamo_audit.py sensitivity
   对31个evaluation题号逐一运行：
   .\\runtime\\python\\python.exe -X utf8 research/mamo_audit.py profile --id 39
   .\\runtime\\python\\python.exe -X utf8 research/mamo_audit.py order --id 39
   将39换成public/problems.json中全部evaluation题号；存在的独立题级检查点自动复用。
   .\\runtime\\python\\python.exe -X utf8 research/mamo_audit_verify.py
   npm run audit:mamo 是以上工作的本地一键入口；--recompute 在新目录从零复算，不覆盖旧账。
3. 图表使用作者环境Python 3.12、Matplotlib与NumPy；版本见plot-environment.json。
   C:\\Users\\30351\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe -X utf8 research/mamo_audit_report.py
4. 所有价格范围是经验损失子水平集的坐标投影，不是置信区间。
   训练损失为mean(suboptimality)/原scale，容差1e-6；分离切平面容差1e-7。
   原始theta盒[0,20]、候选[0,1,2]；求解上下界时无L1，124个边界各留证据。
   inactive-unbounded-price-witnesses.json的100只是诊断见证，未用于原始拟合或评分。
5. 对每题，20个测试情境先平均，再对31道源题等权平均。
   每情境损失max(0,trueCost-oracle)/max(1,abs(oracle))；不剔除离群值。
6. 仅后验诊断：原种子结果、反转排列结果、新历史抽样结果分开保存。
   数据已有结果后制定的审计协议不冒充预注册，区间也不代表跨家族统计推断。
7. 可移植复算：把复现源码放到新目录research，把原始实验_v2放到
   outputs/inverse/mamo-diet-20261020-v2，安装highspy==1.15.1、numpy==2.5.3；
   然后按步骤2运行。图表另用记录的作者环境版本。无需任何密钥。
''',encoding='utf8')
    save(OUT/'plot-environment.json',{'python':sys.version,'matplotlib':importlib.metadata.version('matplotlib'),'numpy':np.__version__,
        'figures':'PNG 180 dpi and vector PDF, all original data retained','xDisplay':'figure 01 panel A linear, B symlog base10 linthresh=1 percent',
        'statisticalUnit':'31 same-family source problems; 20 contexts averaged within each source first'})


if __name__=='__main__':
    d,primary=compile_evidence();figures(d,primary);report(d,primary);package()
    print(json.dumps({'report':str(OUT/'审计报告.html'),'figures':4,'dataRows':len(primary)}))
