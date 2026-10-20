"""Publish every comparison, with seed ranges separated from optimal-face ranges."""
import html
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('MULTIFAMILY_OUT',str(ROOT/'outputs/inverse/multifamily-20261020-v1')))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'work/research/mplconfig'))
sys.path.insert(0,str(ROOT/'work/research/plot-deps'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def read(n):return json.loads((OUT/n).read_text(encoding='utf8'))
LABELS={'fixed_midpoint':'固定中点（不学历史）','known_cost_median':'已知价格中位数（不学历史）','cost_only_io':'正确结构逆优化＊','text_sparse_io':'文本候选＋稀疏逆优化','full_bank_io':'全部候选＋稀疏逆优化','positive_floor_io':'加正价格下限','prior_center_io':'逆优化＋先验居中','projected_subgradient':'投影次梯度（100步）'}
EN=['Fixed midpoint','Known-cost median','Correct-support IO*','Text + sparse IO','Full-bank IO','Positive-floor IO','Prior-center IO','Projected subgradient']
FAMILY={'relocation':'调运题','tour':'闭环路线题'}
def pct(x):return '无界' if x is None else f'{x*100:.3f}%'
def table(headers,rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'

def main():
    d=read('analysis.json');cfg=read('protocol.json');audit=read('source-audit.json');ver=read('verification.json');w=read('optimal-face-witness.json')
    primary=[s for s in d['summaries'] if s['K']==20 and s['noise']==.1]
    methods=cfg['methods']
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white'})
    fig,axes=plt.subplots(2,2,figsize=(15,10),layout='constrained')
    for col,f in enumerate(FAMILY):
        a=axes[0,col];ss=[next(s for s in primary if s['family']==f and s['method']==m) for m in methods]
        yy=np.arange(len(methods));a.barh(yy,[s['mean']*100 for s in ss],color=['#76859a']*2+['#5b9fa8']*4+['#c08438','#4766b0'])
        a.set_yticks(yy,EN);a.invert_yaxis();a.set_xlabel('Default-solver mean regret (%) - lower is better')
        a.set_title(f'{f.title()} | {ss[0]["sources"]} evaluation sources x 5 seeds')
        a.grid(axis='x',alpha=.2)
        for y,s in zip(yy,ss):a.text(s['mean']*100+.06,y,f'{s["mean"]*100:.2f}',va='center',fontsize=9)
        a.set_xlim(0,max(s['mean']*100 for s in ss)*1.2)
        a=axes[1,col]
        pp=[s for s in d['sourceSummaries'] if s['family']==f and s['K']==20 and s['noise']==.1 and s['method']=='text_sparse_io']
        xx=np.arange(len(pp));mid=np.array([s['median']*100 for s in pp]);lo=np.array([s['minimum']*100 for s in pp]);hi=np.array([s['maximum']*100 for s in pp])
        a.errorbar(xx,mid,yerr=np.vstack([mid-lo,hi-mid]),fmt='o',capsize=4,color='#217f89',label='Median and min-max across 5 seeds')
        a.scatter(xx,[s['mean']*100 for s in pp],marker='x',color='#c26a30',label='Mean across 5 seeds')
        a.set_xticks(xx,[s['id'] for s in pp]);a.set_xlabel('Source problem ID');a.set_ylabel('Default-solver regret (%)');a.set_title('Text + sparse IO: every source, no trimmed extremes');a.legend(fontsize=8);a.grid(axis='y',alpha=.2)
    fig.suptitle('Frozen cross-family extension | K = 20, noise gap cap = 10% | exploratory',fontsize=16)
    fig.savefig(OUT/'cross-family-results.png',dpi=180);fig.savefig(OUT/'cross-family-results.pdf');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(15,6),layout='constrained')
    for a,f in zip(axes,FAMILY):
        ss=[next(s for s in primary if s['family']==f and s['method']==m) for m in methods]
        yy=np.arange(len(ss))
        a.hlines(yy,[s['bestTie']*100 for s in ss],[s['worstTie']*100 for s in ss],color='#c16a35',linewidth=4,label='Best-to-worst optimal-face mean')
        a.scatter([s['mean']*100 for s in ss],yy,s=35,color='#2766a5',label='Default solver')
        a.set_yticks(yy,EN);a.invert_yaxis();a.set_xlabel('Regret (%) on estimated optimal face');a.set_title(f'{f.title()} | full linear scale, no clipping');a.grid(axis='x',alpha=.2);a.legend(loc='lower right',fontsize=8)
    fig.suptitle('Oracle-only sensitivity diagnostic - these ranges are NOT confidence intervals',fontsize=14)
    fig.savefig(OUT/'optimal-face-ranges.png',dpi=180);fig.savefig(OUT/'optimal-face-ranges.pdf');plt.close(fig)
    summary=table(['题型／测试题数','方法','平均遗憾','题均值中位数','单次最好／中间／最差','隐价 MAE'],
        [[FAMILY[s['family']]+' / '+str(s['sources']),LABELS[s['method']],pct(s['mean']),pct(s['medianSource']),' / '.join(pct(s[k]) for k in ['minimumRun','medianRun','maximumRun']),f'{s["hiddenMAE"]:.3f}'] for s in primary])
    comparisons=[c for c in d['comparisons'] if c['K']==20 and c['noise']==.1 and c['reference']=='fixed_midpoint']
    compare=table(['题型','方法－固定中点','均差（百分点）','95%探索区间','赢／平／输（题）'],
        [[FAMILY[c['family']],LABELS[c['method']],f'{c["difference"]*100:+.3f}',f'[{c["ci95"][0]*100:+.3f}, {c["ci95"][1]*100:+.3f}]',f'{c["wins"]} / {c["ties"]} / {c["losses"]}'] for c in comparisons])
    audit_table=table(['ID','题型','准入','题面重建最优值','公开答案','理由'],
        [[r['id'],FAMILY[r['family']],r['status'],r.get('reconstructedOptimum','未完整解析'),r['sourceAnswer'],r.get('reason','题面重建与公开答案一致')] for r in audit['records']])
    body=f'''<header><small>LLM4ORTT · 0.1 · 冻结扩展实验 · 2026-10-20</small><h1>跨题型实验：好结果与反例一起交账</h1><p>19 道准入题，5 次重复，8 种方法，3,040 条结果。主比较仅含 16 道测试题：调运 11 道、路线 5 道；另 3 道开发题单独留档。新增付费模型调用：0。</p></header>
<nav><a href="#finding">结论</a><a href="#numbers">完整主比较</a><a href="#inspect">逐题查看</a><a href="#audit">数据准入账</a><a href="paper.html">论文草稿</a><a href="paper.pdf">论文 PDF</a><a href="all-results.csv">下载全部记录</a></nav>
<section id="finding"><h2>现在能说什么</h2><p><b>路线题出现了值得继续验证的信号。</b>文本候选＋稀疏逆优化的平均遗憾为 0.764%，固定中点为 4.271%。5 道题按各自 5 次平均比较，全部改善；配对区间为 −5.139 至 −1.822 个百分点。但只有 5 道同一数据集的准入题，不能说适用于所有路线题。</p>
<p><b>调运题不能宣布稳胜。</b>文本方法平均 5.540%，固定中点 8.118%，差异区间跨零：−13.370 至 +7.093 个百分点。投影次梯度的观察均值最低（1.311%），但相对固定中点的区间也跨零，不能把观察排名写成确定冠军。</p>
<p><b>“费用猜对”和“方案做对”不是一回事。</b>调运题文本方法的隐价 MAE 为 20.106，反而比固定中点的 11.545 差；决策平均遗憾却更低。只报其中一个指标，会把结论说歪。</p>
<p><b>老问题仍在，证据更清楚了。</b>第 44 题第 71 次种子、测试上下文 c24，默认方案真费用 {w['trueDefault']:.3f}；另一同样估计最优的方案真费用 {w['trueWorstExact']:.3f}，遗憾 {pct(w['worstRegretExact'])}。两方案估计费用均为 {w['predictedDefault']:.3f}。这不是画图撑大，而是漏价被估成零后，模型允许免费多调运。<a href="optimal-face-witness.json">查看完整可重算证据</a>。</p>
<p>加入“真实单价至少为 1”的额外先验后，调运最坏最优面平均遗憾从 318.944% 降至 5.145%；这是本次题目的观察结果，不能把先验说成从历史学来的事实，也不能覆盖旧成绩。</p></section>
<section><h2>这次怎样量</h2><p>先冻结题目准入、遮蔽位置、上下界、样本、随机种子、方法和指标，再跑逆优化。所有方法用同一份训练和测试情境。每题遮蔽 2 个真实价格；候选池另加 3 个干扰项。文本使用固定模板，保留 2 个真项和 1 个干扰项；不冒充真实员工日志或大模型理解能力。</p>
<p>主比较用 20 份历史、10% 费用差上限的近优历史。附加条件为 K=5 和无噪声。10% 是每份历史的费用差上限，不是“10% 人犯错”。每次测试 20 个新情境，指标沿用原公式；旧饮食题与旧审计不改、不混进本次总均值。</p>
<p>两种“最好最差”分开：①重新生成 5 批样本所得的最小／中位／最大结果；②同一次预测里，所有估计最优方案的真实费用范围。后者需要知道真值，仅用于验病，部署时不能靠它挑方案。图上区间不是置信区间。</p>
<p>方法＊“正确结构逆优化”预先知道准确的两项位置，属于理想结构诊断。正价下限和居中方法使用额外先验；次梯度只跑固定 100 步，不宣称复现某篇论文的精确算法。“全部候选”只有 5 项，不冒充全矩阵逆优化。</p></section>
<section id="numbers"><h2>完整主比较：不挑冠军，不藏最差</h2><img src="cross-family-results.png" alt="八种方法与每道题的五次范围">{summary}<p>题均值中位数：先将每题 5 次取平均，再对题取中位数。单次范围：该题型全部“题×种子”运行的范围，不是独立题数。</p>
<h3>与不学历史的固定中点相比</h3>{compare}<p>负数表示该方法更好。按原题成组配对重采样 5,000 次；5 次种子先取题内均值，不能当作 5 道新题。区间是探索性百分位 bootstrap，未作多重检验校正；尤其 5 道路线题，外推证据仍薄弱。</p>
<h3>同样最优，实际费用能差多远</h3><img src="optimal-face-ranges.png" alt="所有方法最优方案真实费用区间"><p>完整线性坐标保留所有极端值。调运题文本方法默认均值 5.540%，同样估计最优方案的最坏均值 318.944%。本轮没有出现无界最优面；测试脚本仍覆盖无界反例。</p></section>
<section id="inspect"><h2>逐题、逐条件查账</h2><p>下表包含所有测试题及全部 K／噪声条件，每行 5 次种子。开发题和全部单次详情仍在 CSV 与 JSON 中。</p>
<label>题型 <select id="family"><option value="">全部</option><option value="relocation">调运</option><option value="tour">路线</option></select></label>
<label>方法 <select id="method"><option value="">全部</option>{''.join(f'<option value="{k}">{v}</option>' for k,v in LABELS.items())}</select></label>
<label>K <select id="k"><option value="20">20</option><option value="5">5</option></select></label><label>噪声上限 <select id="noise"><option value="0.1">10%</option><option value="0">0%</option></select></label><div id="detail"></div>
<p>训练历史从未使用的隐藏项：主条件调运题有 58 / 110 个“参数×种子”位置，涉及 9 / 11 道题；路线题 13 / 50 个，涉及 3 / 5 道题。这个计数是激活诊断，不等于已经求出了参数识别区间。未被选择的非负费用项通常只能给下界，不能据此声称已准确恢复。</p></section>
<section id="audit"><h2>59 道候选题的准入账</h2><p>调运 19 道中收 14 道，另 5 道因当前解析器未覆盖或语义矛盾留下原因；不把解析失败一概称为数据错。路线 40 道中，34 道完成解析，其中 29 道的标准闭环巡回最优值不等于公开答案；其余 6 道未完整解析。仅 5 道满足本次准入标准。</p>
<p>34 道已解析路线均用独立的有向 MTZ 整数规划再次求解，与穷举一致。两法共享文本解析和 HiGHS，不能当作两次独立人工语义核验。比如第 61 题，闭环最优为 121，公开答案为 60。全部差异在结果产生前记账，不能为了扩大样本偷偷改答案。</p>{audit_table}</section>
<section><h2>可验材料与不能夸大的地方</h2><p>{ver['checks']:,} 项程序核验通过：冻结哈希、排程完整性、训练与预测可行性、噪声上限、逐条费用和均值。另将第 44 题种子 71 的 32 条结果从头求解，JSON 完全一致。不是 200,076 个独立实验。</p>
<p>保留：本地逆优化管线可运行；路线准入小样本上的改善；最优面歧义与额外先验的影响。暂不成立：所有题稳胜、可靠恢复全部隐价、真实自由文本有效、稀疏性单独有效、已经达到 CCF A 投稿标准。本次没有“只去掉稀疏”的同结构配对方法，因此不能把结构对照当成稀疏消融。</p>
<p><a href="protocol.json">冻结方案</a> · <a href="freeze.json">输入哈希</a> · <a href="analysis.json">全部统计</a> · <a href="verification.json">核验结果</a> · <a href="source-crosscheck-reproduced.json">独立模型复核</a> · <a href="replay-verification.json">重新求解对账</a> · <a href="all-results.json">全部单次结果与测试决策</a></p>
<p>数据来自 MAMO 固定提交 2c91069dee5c1e4db4b899eb176ec987d0251bb3，按 CC BY-SA 4.0 署名分享。新实验版本不替换历史审计，软件版本继续为 0.1。</p></section>'''
    script='''const D=DATA, L=LABELS, F=FAMILY; const p=x=>x===null?'无界':(100*x).toFixed(3)+'%';
function render(){const family=document.querySelector('#family').value,method=document.querySelector('#method').value,k=+document.querySelector('#k').value,noise=+document.querySelector('#noise').value;
const rows=D.filter(r=>(!family||r.family===family)&&(!method||r.method===method)&&r.K===k&&r.noise===noise);
document.querySelector('#detail').innerHTML='<div class="scroll"><table><thead><tr>'+['ID','题型','方法','均值','最好','中间','最差','最优面最坏均值','未激活项数范围'].map(t=>'<th>'+t+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+[r.id,F[r.family],L[r.method],p(r.mean),p(r.minimum),p(r.median),p(r.maximum),p(r.worstTie),r.unusedHiddenMin+'–'+r.unusedHiddenMax].map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
document.querySelectorAll('select').forEach(s=>s.addEventListener('change',render));render();'''
    script=script.replace('DATA',json.dumps(d['sourceSummaries'],ensure_ascii=False)).replace('LABELS',json.dumps(LABELS,ensure_ascii=False)).replace('FAMILY',json.dumps(FAMILY,ensure_ascii=False))
    css='body{font:17px/1.8 system-ui,"Microsoft YaHei",sans-serif;background:#edf2f5;color:#172a39;margin:0}header,section,nav{max-width:1250px;margin:24px auto;padding:28px;background:white;border-radius:12px}header{background:#17364b;color:white}h1{font-size:36px}h2{font-size:26px;border-bottom:2px solid #dbe7ed;padding-bottom:10px}a{color:#087e95}nav{display:flex;gap:25px;flex-wrap:wrap}img{width:100%;height:auto}.scroll{overflow:auto}table{border-collapse:collapse;font-size:14px;width:100%}th,td{padding:9px 12px;text-align:left;border-bottom:1px solid #e0e8ee;white-space:nowrap}th{background:#edf3f6}select{padding:8px;margin:8px}p{max-width:1100px}@media(max-width:700px){header,section,nav{margin:10px;padding:18px}h1{font-size:26px}}'
    css+='p{overflow-wrap:anywhere}select{max-width:calc(100% - 16px)}'
    (OUT/'跨题型报告.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>跨题型实验：完整结果与反例</title><style>'+css+'</style>'+body+'<script>'+script+'</script></html>',encoding='utf8')
    print(json.dumps({'report':str(OUT/'跨题型报告.html'),'figures':4}))

if __name__=='__main__':main()
