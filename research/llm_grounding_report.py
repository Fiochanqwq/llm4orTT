"""Generate the complete report from preserved outcomes; never change scores."""
import csv, json, html, statistics as st, sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/inverse/deepseek-grounding-20261020-v1'
sys.path.insert(0,str(ROOT/'work/research/plot-deps'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.collections import PathCollection

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def esc(v):return html.escape(str(v))
def pct(v):return '缺失' if v is None else f'{v*100:.3f}%'
def number(v):return '缺失' if v is None else f'{v:.4f}'
LABELS={
 'zero':'全报 0','unit':'全报 1','random':'固定随机数','all_io':'完整候选库＋逆优化',
 'ds_io':'DS 原提示＋逆优化','ds_no_l1':'DS 去掉稀疏惩罚','no_logs_io':'DS 原提示无日志',
 'shuffled_io':'DS 原提示错配日志','ds_anchor':'DS 数值先验锚定','oracle_structure_io':'真结构＋逆优化',
 'subgradient':'DS＋50 步次梯度','ds_direct':'DS 直接猜数','ds_feedback':'DS 一轮反馈修改',
 'ds_clarified_io':'DS 澄清提示＋逆优化','clarified_no_logs_io':'DS 澄清提示无日志',
 'clarified_shuffled_io':'DS 澄清提示错配日志'}
ORDER=list(LABELS);COLLECTIONS=['NL4Opt','MAMO','OptMATH']
COLORS=['#0072B2','#D55E00','#009E73']
def table(headers,rows):
    return '<div class="scroll" tabindex="0"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table></div>'
def link(path,label=None):return '<a href="'+esc(path)+'">'+esc(label or path)+'</a>'
def image(name,caption):return '<figure><a href="figures/'+name+'.svg"><img loading="lazy" src="figures/'+name+'.png" alt="'+esc(caption)+'"></a><figcaption>'+esc(caption)+'</figcaption></figure>'
def figure_save(fig,name):
    for ax in fig.axes:
        xlo,xhi=sorted(ax.get_xlim());ylo,yhi=sorted(ax.get_ylim())
        for artist in ax.collections:
            if isinstance(artist,PathCollection):
                for x,y in artist.get_offsets():
                    assert xlo-1e-8<=x<=xhi+1e-8 and ylo-1e-8<=y<=yhi+1e-8,(name,'clipped observation',float(x),float(y),ax.get_xlim(),ax.get_ylim())
    fig.savefig(OUT/'figures'/f'{name}.png',dpi=170)
    fig.savefig(OUT/'figures'/f'{name}.svg')
    plt.close(fig)
def csv_write(name,rows,fields):
    with (OUT/'tables'/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def figures(a,rows):
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':10,
                         'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none',
                         'savefig.facecolor':'white'})
    (OUT/'figures').mkdir(exist_ok=True);(OUT/'tables').mkdir(exist_ok=True)
    pa=[]
    for c in COLLECTIONS:
        for mode in ['proposal','no_logs','shuffled','clarified','clarified_no_logs','clarified_shuffled']:
            q=[p for p in a['proposalAudit'] if p['collection']==c and p['mode']==mode]
            pa.append({'collection':c,'mode':mode,'n':len(q),'valid':sum(p['status']=='valid' for p in q),
                       'F1':st.mean(p.get('structure',{}).get('f1',0) for p in q)})
    fig,axes=plt.subplots(1,3,figsize=(14,4.8),layout='constrained')
    for ax,c in zip(axes,COLLECTIONS):
        for j,(ms,label,color) in enumerate([(['proposal','no_logs','shuffled'],'原提示','#0072B2'),
                                            (['clarified','clarified_no_logs','clarified_shuffled'],'澄清提示（事后）','#D55E00')]):
            rr=[next(p for p in pa if p['collection']==c and p['mode']==m) for m in ms]
            xx=np.arange(3)+(j-.5)*.36
            ax.bar(xx,[p['F1'] for p in rr],width=.34,color=color,label=label,hatch='' if j==0 else '//')
            for x,p in zip(xx,rr):
                ax.text(x,p['F1']+.025,f'{p["F1"]:.2f}\n{p["valid"]}/{p["n"]}',ha='center',fontsize=9)
        ax.set(xticks=range(3),xticklabels=['本题日志','没有日志','错配日志'],ylim=(0,1.22),title=c)
        ax.set_ylabel('候选目标项 F1；无效输出记 0');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    axes[0].legend(loc='upper right',fontsize=8)
    figure_save(fig,'01-text-structure')
    csv_write('structure-conditions.csv',pa,['collection','mode','n','valid','F1'])

    primary=[r for r in rows if r['K']==10 and r['noise']==.1 and r['status']!='blocked_source']
    fig,axes=plt.subplots(1,3,figsize=(18,10.8),layout='constrained')
    for ax,c,color in zip(axes,COLLECTIONS,COLORS):
        labels=[]
        for j,m in enumerate(ORDER):
            rr=[r for r in primary if r['collection']==c and r['method']==m];good=[r for r in rr if r['status']=='complete']
            values=[r['meanRegret']*100 for r in good]
            yy=j+np.linspace(-.18,.18,len(good)) if good else []
            ax.scatter(values,yy,s=24,color=color,alpha=.7,marker='o',edgecolors='white',linewidths=.35)
            summary=next(s for s in a['primarySummaries'] if s['collection']==c and s['method']==m)
            if summary['mean'] is not None:ax.scatter([summary['mean']*100],[j],marker='D',s=44,c='#111111',zorder=4)
            labels.append(f'{LABELS[m]}  {len(good)}/{len(rr)}')
        ax.set_xscale('symlog',linthresh=1,base=10)
        ax.set(yticks=range(len(ORDER)),yticklabels=labels,title=c,xlabel='平均决策遗憾（%），越小越好')
        ax.invert_yaxis();ax.set_xlim(left=0);ax.grid(axis='x',alpha=.2)
        ax.tick_params(axis='y',labelsize=9)
    fig.suptitle('全部 16 种办法｜每点＝一道题×一个历史种子；黑菱形只画完整队列均值\n横轴 0–1% 线性，超过 1% 按 10 倍刻度；行末为完成数/计划数，失败没有算成 0',fontsize=13)
    figure_save(fig,'02-all-methods')

    fig,axes=plt.subplots(1,2,figsize=(13,5.8),layout='constrained',sharex=True,sharey=True)
    for ax,m in zip(axes,['ds_io','ds_clarified_io']):
        for j in range(1,9):
            rr=[r for r in primary if r['id']==f'mamo-{j}' and r['method']==m]
            gg=[r for r in rr if r['status']=='complete']
            ax.scatter([r['meanRegret']*100 for r in gg],[j+(-.08 if r['seed']==19 else .08) for r in gg],
                       c='#D55E00',s=50,edgecolors='white')
            ax.text(1.01,j,f'{len(gg)}/2',transform=ax.get_yaxis_transform(),fontsize=10,va='center')
        ax.set(yticks=range(1,9),yticklabels=[f'mamo-{j}' for j in range(1,9)],title=LABELS[m],
               xlabel='平均决策遗憾（%）：完整线性坐标，没有截掉大数')
        ax.grid(axis='x',alpha=.2)
    all_mamo=[r['meanRegret']*100 for r in primary if r['collection']=='MAMO' and r['method'] in ['ds_io','ds_clarified_io'] and r['status']=='complete']
    axes[0].set_xlim(0,max(all_mamo)*1.08)
    axes[0].set_ylim(8.5,.5)
    fig.suptitle('MAMO 的巨幅损失保留全貌｜原提示 mamo-6 没跑成，不代表它得分为 0')
    figure_save(fig,'03-mamo-full-scale')

    selected=[('ds_clarified_io','unit'),('ds_clarified_io','all_io'),
              ('ds_clarified_io','clarified_no_logs_io'),('ds_clarified_io','clarified_shuffled_io'),
              ('ds_feedback','ds_io')]
    fig,axes=plt.subplots(1,3,figsize=(17,6.0),layout='constrained')
    short=['澄清版 − 全报 1','澄清版 − 完整候选库','澄清版 − 无日志','澄清版 − 错配日志','反馈版 − 原版']
    for ax,c in zip(axes,COLLECTIONS):
        labels=[]
        for j,(l,r) in enumerate(selected):
            q=next(x for x in a['contrasts'] if x['collection']==c and x['left']==l and x['right']==r)
            v=q['meanDifference']*100;lo,hi=np.array(q['ci95'])*100
            ax.errorbar([v],[j],xerr=[[max(0,v-lo)],[max(0,hi-v)]],fmt='o',capsize=5,color='#0072B2')
            labels.append(short[j]+f'  n={q["n"]}')
        ax.axvline(0,color='#333',linestyle='--');ax.set(yticks=range(len(selected)),yticklabels=labels,title=c,
            xlabel='遗憾差（百分点）；左边有利于前者')
        ax.invert_yaxis();ax.grid(axis='x',alpha=.2)
    fig.suptitle('只比较双方都完成的同一道题｜先对两种子平均，再按题 bootstrap 5,000 次\n95% 探索性区间，未校正多重比较；不同面板横轴范围不同')
    figure_save(fig,'04-paired-uncertainty')

    fig,axes=plt.subplots(1,3,figsize=(14,5),layout='constrained')
    for ax,c in zip(axes,COLLECTIONS):
        for m,marker,color,label in [('ds_io','o','#0072B2','原提示'),('ds_clarified_io','^','#D55E00','澄清提示')]:
            rr=[r for r in primary if r['collection']==c and r['method']==m and r['status']=='complete']
            ax.scatter([r['relativeMAE']*100 for r in rr],[r['meanRegret']*100 for r in rr],marker=marker,c=color,label=label,alpha=.75)
        ax.set_xscale('symlog',linthresh=1);ax.set_yscale('symlog',linthresh=1)
        ax.set(xlabel='真目标项参数相对 MAE（%）',ylabel='决策遗憾（%）',title=c,xlim=(0,None),ylim=(0,None))
        ax.grid(alpha=.15)
    axes[0].legend()
    fig.suptitle('决策看起来好，不等于把价格学对｜两个坐标 0–1% 线性，之后为 10 倍刻度；零值保留')
    figure_save(fig,'05-price-vs-decision')
    save(OUT/'figures/figure-metadata.json',{
        'purpose':'General research report, no conference-format claim','primarySlice':{'K':10,'noiseCap':.1},
        'plotRuntime':{'python':sys.version,'matplotlib':matplotlib.__version__,'numpy':np.__version__},
        'source':'../all-results.json and ../analysis.json','noRowsRemovedForAppearance':True,
        'allScatterObservationsWithinAxisBounds':True,
        '01':'F1 average over all admitted source proposals, invalid proposal=0; exact typed objective terms, not constraints.',
        '02':'All successful primary source-seed rows shown; failures only in numerator labels. Full-cohort mean only if complete. x symlog base10 linthresh1 percentage point.',
        '03':'Full linear view of all successful MAMO source-seed rows for original and clarified prompts; no clipping.',
        '04':'Source-paired bootstrap5000, seed20261020. Complete pairs only; missing IDs in contrasts JSON. Unadjusted exploratory intervals. Panel axes not shared.',
        '05':'All successful original/clarified source-seed primary rows; both axes symlog threshold1 percentage point. No formal identifiability claim.'})
    return pa

def main():
    a=read(OUT/'analysis.json');rows=read(OUT/'all-results.json')
    if '--html-only' not in sys.argv:figures(a,rows)
    source=read(OUT/'source-audit.json');refs=read(ROOT/'research/llm_grounding_references.json')
    repair=read(OUT/'solver-repair-checks.json');mech=read(OUT/'mechanism-diagnostics.json');control=read(OUT/'mechanism-control.json')
    api=a['api'];primary=a['primarySummaries']
    csv_write('all-configurations.csv',a['summaries'],list(a['summaries'][0]))
    csv_write('source-min-median-max.csv',a['sourceSummaries'],list(a['sourceSummaries'][0]))
    csv_write('all-failures.csv',a['failures'],['id','collection','seed','K','noise','method','status','error'])
    csv_write('paired-comparisons.csv',a['contrasts'],list(a['contrasts'][0]))
    methods=[
      ('zero / unit / random','在完整候选库内分别全报 0、全报 1、固定随机数，不读取历史。','候选库给了隐藏线性项的正确符号及设计门槛；不是完全无结构知识。'),
      ('all_io','完整候选库＋稀疏次优性损失，λ=0.01。','只有声明的少量监测项；不叫“传统全矩阵逆优化”。'),
      ('ds_io','真实 DS 根据日志给候选公式，本地求参数。','一次生成复用于两种子；候选错号也照样保留。'),
      ('ds_no_l1','同一候选公式，λ=0。','与 ds_io 配对看稀疏惩罚是否必要。'),
      ('no_logs_io / shuffled_io','重新调用 DS；分别不给日志、给同库循环错配日志。','所有物理模型和历史保持相同。'),
      ('ds_anchor','DS 直接数值猜测作先验；ε 不敏感损失＋0.02 L1 锚定。','只用 K=10；是组合基线，不是 Wasserstein DRO。'),
      ('oracle_structure_io','直接提供真实目标项，仍用历史估计权重。','信息更强的诊断对照，不是假装现实可得。'),
      ('subgradient','DS 候选，50 次投影循环次梯度，训练损失选迭代点。','盒约束 [0,20]；不继承论文不同假设下的精确有限步保证。'),
      ('ds_direct','真实 DS 看到 10 组历史后直接猜权重；猜测时没有求解器。','候选来自原始 DS 生成；初始候选失效会阻断数值猜测。'),
      ('ds_feedback','只把训练残差最大的 3 例或编译错误交给 DS，修一次，再拟合。','同一轮全部结果保留；未使用测试真值选择是否接受。'),
      ('ds_clarified_io / clarified_no_logs_io / clarified_shuffled_io','事后统一澄清“未知价格必须留参数、没有默认门槛”，再做本题/无/错配日志。','每条件每题一次 API，无多次抽奖选最佳；仍属探索。')]
    body=[]
    body.append(f'''<header><div class="eyebrow">LLM4ORTT 0.1.0 · 2026-10-20 · 独立新批次</div>
<h1>让 DeepSeek 真正参与建模，<br>也把它算错的地方摆出来。</h1>
<p class="lead">三套公开题目、真实 API、16 种方法与消融。旧实验没有覆盖，本轮好坏结果一起交付。</p>
<div class="cards"><div><strong>{api['attempts']}</strong>真实 API 请求</div><div><strong>27 / 28</strong>通过准入的题目</div>
<div><strong>{a['scheduled']:,}</strong>计划结果行（非独立题目）</div><div><strong>¥{api['tokenBasedCNYRange'][0]:.2f}–{api['tokenBasedCNYRange'][1]:.2f}</strong>按 token 估算，非账单</div></div></header>
<nav><a href="#verdict">先看结论</a><a href="#llm">LLM 做了什么</a><a href="#design">怎么比</a><a href="#results">全部成绩</a>
<a href="#failures">翻车账本</a><a href="#mechanisms">错在哪里</a><a href="#limits">哪些话得收回</a><a href="#evidence">证据与复算</a></nav>''')
    body.append('''<section id="verdict"><h2>先把话说实在</h2>
<div class="verdict"><strong>这次与 LLM 有直接关系了；但“LLM 加进来就比笨办法强”，还没有被证明。</strong>
<p>DeepSeek 真正写了运营日志、读日志生成未知参数公式、直接猜价格、接收训练反馈并修改公式。数学程序负责求参数和检验结果。两边各自做了什么，都有原始记录。</p></div>
<ul><li><b>站得住的局部发现：</b>在 OptMATH 路线题的澄清提示组，本题日志的平均决策遗憾为 3.499%，没有日志为 21.075%；同题配对差的探索性 95% 区间为 −28.866 至 −8.365 个百分点。这说明本组日志有信息，不能推广为所有题都有效。</li>
<li><b>但没有证明恢复了路线的隐性惩罚：</b>7 道路线题的真实软惩罚在两个种子的全部训练、测试观测决策上都没有触发。文字帮助找到了成本项等结构，不能把收益归功于学会了复杂软约束。</li>
<li><b>没有赢过最朴素对照：</b>同组“全报 1”为 1.196%，比 3.499% 还低。澄清版相对全报 1 的配对区间跨零，不能宣称稳定胜出。</li>
<li><b>最难看的结果：</b>MAMO 澄清版完成 15/16 次，成功部分平均遗憾 290.839%；完整均值缺失。不能拿它跟原版成功部分 13/16 的均值直接说进步。mamo-6 的两次结果都坏，不是只碰到一次坏运气。</li>
<li><b>反馈循环没交出胜利：</b>可完整配对的题上，反馈在 NL4Opt 全部打平，在 MAMO、OptMATH 各有变差的题，没有改善的题。能修到可运行，不等于能修到更准。</li></ul>
<p><b>数学估计也有可保留的局部作用：</b>固定原始 DS 候选后，逆优化对比 DS 直接猜数，在可完整配对的 MAMO 6 题、OptMATH 6 题上，平均遗憾分别少 70.009、9.800 个百分点，探索性区间不跨零；NL4Opt 不支持稳定差异。这只比较成功配对题，不能替漏掉/写错公式的题洗白。</p>
<p class="plain">打个比方：这次确实请了“读便条的师傅”来帮忙。但他有时把“付款”听成“收钱”。计算器再认真，也会沿着错账算下去。</p></section>''')
    body.append('<section id="llm"><h2>LLM 的真实工作，不再拿人工规则冒充</h2>'+table(
        ['API 阶段','请求数','成功 JSON','输入 token','输出 token'],
        [[esc(k),v['attempts'],v.get('ok',0),f'{v["input"]:,}',f'{v["output"]:,}'] for k,v in api['byStage'].items()])+
        '''<p>服务端返回模型名统一为 <code>deepseek-flash</code>；thinking 关闭，temperature=0，最多输出 2,000 token，60 秒超时，并发 3，不自动重试。397 次中 394 次返回通过顶层 JSON 检查，3 次 JSON 无效。返回 JSON 不等于公式正确，也不等于后续求解成功。</p>
<p>真实 API 的证据是 <code>llm/raw/</code> 中逐次提示、返回文本、responseId、开始/结束时间、token 用量与状态。没有把 API 密钥或用户聊天放进证据包。</p>
<p><b>日志是受控合成的：</b>写日志的调用只看到定性事实和业务门槛，不知道隐藏价格；读日志的调用只看到已知物理模型、监测项定义和日志，不见 Oracle 权重、原题答案或测试集。生成与理解均使用同一模型，存在自洽偏差。没有真人运营日志或专家盲审。“本题日志”只表示题目对应正确，不保证生成内容语义无误；下文保留了生成日志引入歧义的例子。</p>'''+
        image('01-text-structure','上方数字为候选目标项 F1，下方为可编译输出数/题目数；无效输出计 0。F1 同时匹配变量、正负号、监测项和门槛，评的是目标项结构，不是硬约束召回。澄清提示是事后探索。')+'</section>')
    body.append('''<section id="design"><h2>题目、输入与公平比较的边界</h2>'''+table(
        ['公开集合','固定候选','准入','本轮含义'],
        [['NL4Opt','官方测试文件前 12 条','12 / 12','2 变量连续 LP；来自人工标注结构，最大化统一转为最小化'],
         ['MAMO','编号 1 至 8','8 / 8','整数配餐；原目标值与公开答案一致'],
         ['OptMATH','2, 8, 29, 33, 63, 65, 93, 124','7 / 8','有向巡回路线；93 无法完整解析，不替补']])+'''
<p>新增下载了 NL4Opt 与 OptMATH 的官方数据。三库均只抽取当前解析器支持的小规模题型；这是 27 道固定子集，不能代表整套基准。NL4Opt 不是原计划 OptiMUS/NLP4LP 的 100 题；本轮也未覆盖 K=20 或 5%/15% 噪声，不能冒称原大方案已经完成。题目身份、源码 revision、下载失败和文件 SHA256 都保留。</p>
<p>每题遮住 <b>1 个原目标系数</b>，另加 <b>1 个实验设计的软惩罚</b>。软惩罚不是原公开题目自带标注。已知系数按其非零绝对值中位数归一化；历史和测试场景将已知成本乘以 U(0.5,1.5)，物理可行域不变。隐藏参数取值盒为 [0,20]。</p>
<p>每题种子 19、43，各有 10 组训练上下文与 10 组不重叠测试上下文；K=5 使用训练前 5 组，K=10 使用全部。每题的 LLM 候选在两个历史种子间复用，所以不能把它们当作两次独立 LLM 抽样。</p>
<p>噪声条件为 0 或 0.1：含噪历史仍然可行，真实目标与最优值的差不超过 0.1×max(1,|最优值|)。这是“最差多损失 10% 的受控选择”，不是“10% 的员工乱填”，也不是通用的人类噪声模型。所有方法使用相同上下文与历史。</p>
<div class="formula">前向：min<sub>x∈X</sub> b<sub>k</sub><sup>T</sup>x + Σ θ<sub>j</sub> φ<sub>j</sub>(x)<br>
φ 是带符号的线性项，或 max(0, a<sup>T</sup>x − 门槛)。<br>
逆向：min<sub>0≤θ≤20</sub> 平均归一化次优性残差 + 0.01 × Σθ<sub>j</sub>/20</div>
<p>每次用经过最优性认证的前向求解发现违反的比较约束，加入逆模型。连续与整数题均用此分离策略；整数问题没有假套连续 KKT。路线题枚举全部巡回方案，其余由 HiGHS 求解。最多 60 轮、拟合 60 秒、单次前向 5 秒，超过或无法认证均留为失败。</p>
<p><b>LLM 只负责受限公式语言：</b>变量、物理约束与候选监测项已给定。它选择目标项、符号和门槛，不负责自由生成完整数学模型。不执行 LLM 写出的 Python。</p>'''+
        table(['办法','真正做的事','必须说明的限制'],[[esc(x) for x in r] for r in methods])+'''
<h3>设计变更也留账</h3>
<ol><li>原始方案和题目在方法成绩出现前冻结，保留 protocol 与输入哈希。</li>
<li>数值先验看了 10 组历史，所以把 ds_anchor 限定到 K=10；没有让 K=5 偷看额外历史。</li>
<li>初始模型失败时没有残差可回传：补充允许用编译/拟合错误和训练历史进行一次反馈，共涉及 9 个来源×种子×噪声组合。这是有记录的探索性修订。</li>
<li>发现“缺价就不计价”“重复收已知费用”“照抄示例门槛 1.2”后，固定澄清提示，全部 27 题都再做本题/无/错配日志，共 81 次 API。没有按测试分数挑提示赢家。这仍是事后探索，须在新题验证。</li></ol>
<p>原方案 2,576 行，澄清组追加 336 行，共 2,912 行。完整配置与逐题最小/中位/最大值在表格文件中；这不是 2,912 道独立题。</p></section>''')
    summary_rows=[]
    for c in COLLECTIONS:
        for m in ORDER:
            q=next(q for q in primary if q['collection']==c and q['method']==m)
            summary_rows.append([c,esc(LABELS[m]),f'{q["complete"]}/{q["scheduled"]}',pct(q['mean']),
                pct(q['successfulOnlyMean']),pct(q['min']),pct(q['median']),pct(q['max']),pct(q['relativeMAE'])])
    body.append('''<section id="results"><h2>全部主条件成绩</h2>
<p>主条件固定为 K=10、噪声上限 0.1，各库分别汇总。完整均值先对同题两种子平均，再对题平均；只要有预定运行缺失，完整均值就显示“缺失”。成功部分均值仅供诊断，不能拿不同缺失子集做排名。</p>
<div class="formula">决策遗憾 = max(0, 真实目标值 − Oracle 最优值) / max(1, |Oracle 最优值|)<br>
参数相对 MAE = 真目标项参数绝对误差的平均 / 真实参数的平均。漏掉或错号的真项估为 0；假项权重另记 nuisanceWeight。</div>
<p>所有百分数都按固定公式计算。超过 100% 表示相对损失超过参照值，不是程序把比例截成 100%。最大化题变号后目标可为负；没有把负收益当正支出解读。MAE 用归一化模型单位，不是原始币值。余弦相似度本轮没有作为已完成指标。</p>'''+
        image('02-all-methods','所有主条件完成行都画出，没有裁掉离群点。黑菱形只画完整队列均值，失败不当零。为了同时看见零和大数，横轴明确采用分段线性/对数刻度；各面板范围由本库全部值决定。')+
        table(['题库','办法','完成/计划','完整均值','成功部分均值','最小','中位','最大','参数相对 MAE¹'],summary_rows)+
        '<p class="note">¹ 参数误差同样只汇总成功行。最小/中位/最大描述的是“每题×种子的十个测试场景平均遗憾”的分布；单个测试场景极值在原始 tests 数组中。</p>'+
        image('03-mamo-full-scale','MAMO 完整线性坐标补图。澄清后 mamo-6 两种子平均遗憾分别为 2,068.075% 和 1,988.083%；原提示该题因输出超出 8 项上限失败。不能把失败消失当作低误差。')+
        image('04-paired-uncertainty','区间来自同题的两种子平均，再按题重抽 5,000 次。n 是完整配对题数，缺失题不进入比较，名单在 paired-comparisons.csv。区间跨零说明当前样本不能支持稳定方向；这些区间未校正多重比较，也不是论文级确认。')+
        '<details><summary>展开全部配对比较的数字</summary>'+table(
            ['题库','前者 − 后者','完整配对题数','平均差（百分点）','95% 区间','前者赢/平/输','缺失题'],
            [[q['collection'],esc(LABELS[q['left']]+' − '+LABELS[q['right']]),q['n'],
              f'{q["meanDifference"]*100:.3f}',f'[{q["ci95"][0]*100:.3f}, {q["ci95"][1]*100:.3f}]',
              f'{q["wins"]}/{q["ties"]}/{q["losses"]}',esc(', '.join(q['omittedIds']) or '无')] for q in a['contrasts']])+
        '</details><p>'+link('tables/all-configurations.csv','所有 K 与噪声条件')+' · '+link('tables/source-min-median-max.csv','每道题的最小/中位/最大值')+' · '+link('all-results.csv','全部逐次结果')+'</p></section>')
    errors=Counter(r['error'] for r in a['failures'])
    body.append(f'''<section id="failures"><h2>失败、卡点与资源，全部记账</h2>
<p><b>{a['statusCounts']['complete']:,} 行完成，{a['statusCounts']['failed']} 行方法失败，{a['statusCounts']['blocked_source']} 行因来源未准入被阻断。</b>
来源阻断均来自 OptMATH 93，不能说成 104 次算法翻车。API 的 3 次无效 JSON 会影响多个历史条件，不能把 API 失败数与实验行失败数相加。</p>'''+
        table(['原因','受影响的计划行'],[[esc(k),v] for k,v in errors.items()])+'''
<p>超出 8 项上限、变量名不合法或符号错误均保留；无界/不可认证也不悄悄改成有限答案。错配日志输出失败和正规日志输出失败采用相同记录口径。</p>
<h3>一个真工程错误，以及独立复查</h3>
<p>5 行遇到 <code>Error adding constraint to the model.</code>。复现的逆优化割中有约 10⁻¹⁶ 的系数，HiGHS 高层接口把非 kOk 的 addRow 返回当异常。另写了带参数盒下界补偿的稀疏割实现：丢弃 |a|≤10⁻⁹ 的系数并补上这些项在 [0,20] 上的最小值，继续用完整残差检查 10⁻⁶ 容差。这样不会把丢弃的小项凭空当零。</p>
<p>这 5 行在独立复查中全部拟合并完成测试。<b>主表中的 5 个失败没有被覆盖，也没有混入修复成绩。</b>修复代码和每行重新计算的成绩单独存放。第一次诊断运行还遇到 NumPy 整数不能序列化，修复后才保存成功；没有生成可用的首版诊断成绩。</p>'''+
        table(['题目','种子','办法','修复后状态','修复后遗憾（单独诊断）'],
              [[r['id'],r['seed'],esc(LABELS[r['method']]),r['repairStatus'],pct(r.get('score',{}).get('meanRegret'))] for r in repair['results']])+f'''
<h3>钱和算力</h3>
<p>输入 {api['tokens']['input']:,} token，其中缓存命中 {api['tokens']['cacheHit']:,}；输出 {api['tokens']['output']:,} token。
按官方文档的峰时与谷时单价估算共 ¥{api['tokenBasedCNYRange'][0]:.4f}–¥{api['tokenBasedCNYRange'][1]:.4f}；所有请求都有返回用量。没有读取实际账户发票，所以不能把估算说成扣款数。</p>
<p>主要本地评估工作进程合计 CPU {a['resources']['workerCPUSeconds']:.2f} 秒，工作进程墙钟时间之和 {a['resources']['workerWallSecondsSum']:.2f} 秒，前向调用 {a['resources']['forwardCalls']:,} 次，记录的求解器时间 {a['resources']['solverSeconds']:.2f} 秒。墙钟之和含并发，不能当成用户实际等待时长。这些数不含 API 等待、历史准备、分析、画图和打包；整机耗电未测。机制复查另有 CPU/墙钟记录，首次失败诊断的 CPU 未单独计量。</p>
<p>下载公共源时原始下载端点曾失败，随后按官方 GitHub API 的 revision 和 blob 下载，原失败见 source-data/llm-grounding-v1/download-manifest.json。早期准备脚本曾遇到导入路径与 MAMO 编号 0 不存在，均在最终输入冻结前修正，不据成绩替换题目。</p>
<p>所有逐行失败：{link('tables/all-failures.csv')}；工程修复：{link('solver-repair-checks.json')}；原错误复现：{link('cut-failure-diagnostic.json')}。</p></section>''')
    activation=[]
    for c in COLLECTIONS:
        rr=[r for r in mech['activation'] if r['collection']==c]
        for part in ['trainOracle','trainNoisy','testOracle']:
            for j,name in enumerate(['隐藏单价项','合成软惩罚项']):
                zero=[r for r in rr if r[part+'Activation'][j]==0]
                both=[sid for sid in sorted({r['id'] for r in rr}) if all(r[part+'Activation'][j]==0 for r in rr if r['id']==sid)]
                activation.append([c,part,name,f'{len(zero)}/{len(rr)}',esc(', '.join(both) or '无')])
    signrows=[r for r in control['results'] if r['noise']==.1]
    body.append('''<section id="mechanisms"><h2>“分数好、账却错”和“不同方案像一样”，有了具体凭据</h2>
<h3>例 1：苹果成本的正负号被读反</h3>
<p><code>mamo-6，seed=19，K=10，noise=0.1，澄清提示</code>。原始定性事实只说 Apples 的单价缺失；日志生成又加了“don't ... slot in a placeholder”，给下游造成了不必要的歧义。澄清提示已经明确单位成本用 +1，但 DS 仍返回 Apples 的 sign=−1。真实项是正成本，非负权重盒下无法用负号表示正成本。</p>
<p>拟合得到两个权重都为 0。测试场景 <code>mamo-6-s19-c18</code> 选了 90 单位苹果，模型记账 0，真实目标 75，Oracle 为 2.43943846，遗憾为 2,974.478%。另一历史种子也坏：不是只抽到一组倒霉历史；但两种子复用同一个 LLM 输出，不能据此说模型重复生成都会犯错。</p>
<p>原始日志、候选、真值和具体决策都在：'''+link('llm/logs/mamo-6.json','日志')+' · '+link('llm/clarified/mamo-6.json','DS 公式')+' · '+link('oracle/mamo-6.json','Oracle')+' · '+link('clarified-results/mamo-6-s19.json','逐次结果')+'''。</p>
<p><b>定点因果诊断：</b>对所有澄清候选里成本符号错的 4 道题，两个种子、两种噪声均做一次“只给正确符号”的干预，其他历史、门槛、权重盒和 λ 保持不变。干预前后都使用同一个稀疏割修复实现，避免把求解器修复混成符号收益。这个额外符号来自 Oracle，明确是查原因，不能充当 LLM 自己学会了。</p>'''+
        table(['题目','种子','原始冻结成绩','同求解器、符号未改','同求解器、只改符号'],
              [[r['id'],r['seed'],pct(r['frozenMeanRegret']),pct(r.get('originalFeaturesStableScore',{}).get('meanRegret')),pct(r['signCorrectedMeanRegret'])] for r in signrows])+'''
<p>mamo-6 修正符号后从两千%左右降到个位数百分比，支持错误符号是主要故障来源；mamo-7 修正符号后反而变差，说明正确结构加上含噪有限历史与稀疏估计，也不保证测试决策更好。这个反向结果同样保留。</p>
<h3>例 2：决策损失不到 1%，价格却错得很远</h3>
<p><code>mamo-7，seed=43，澄清提示</code>：平均决策遗憾 0.895%，真目标项参数相对 MAE 却是 246.978%。生成的 Food_4 成本符号错误，拟合把该项设为 0，另一软惩罚权重拟合为 12.0416。当前测试选择表现好，只说明某些方案还选得过去，不代表从历史中恢复了正确价格。</p>'''+
        image('05-price-vs-decision','横轴表示真参数项误差，纵轴表示方案遗憾。横向很远但纵向接近零的点，是“选得还行、账没学对”的直接证据。缺失或失败行没有作为零点加入。')+'''
<h3>例 3：它把两份明显不同的方案算成同一个价</h3>
<p><code>nl--450888040，seed=43，测试 c13，原提示 DS</code>：方案 A=[500,0]，另一个已观察方案 B=[500,166.6667]。DS 模型给两者同样的目标值 −16.2564；真实目标分别为 −312.3798 和 −489.4810，相差归一化 36.181%。这里原题最大化已变号，真实目标越小越好。模型漏掉或压掉有区分作用的项，会把不同收成算成一样。</p>
<p>这里只给“已经观察到的另一方案”作为反例，没有宣称求到了整个最优面的最坏方案。</p>
<h3>有些“价格”，在这批选择里根本没有被用到</h3>
<p>下表逐项统计真实特征在观测决策上为零的次数。两个种子都不出现的题目直接列名；明细保留每组 10 个场景的激活数量。尤其路线题的软惩罚经常不激活，不能拿漂亮的路线分数来证明学会了复杂隐性偏好。</p>'''+
        table(['集合','观察部分','真目标项','完全不激活的题×种子','两个种子均不激活的题目'],activation)+'''
<p><b>零激活不是不可辨识性的数学证明：</b>没选中的竞争方案仍可能触发该项，提供参数下界。本轮没有逐题计算完整识别区间，所以只报告暴露不足，不说“这些参数一定学不出来”。</p>
<p>完整机制证据：'''+link('mechanism-diagnostics.json')+' · '+link('mechanism-control.json','同求解器干预对照')+' · '+link('analysis.json','含同价反例与低遗憾错价格清单')+'</p></section>')
    body.append('''<section id="limits"><h2>哪些话还站得住，哪些必须收回</h2>'''+table(
        ['判断','本轮结论'],
        [['“这次没有真正用 LLM”','已改变：397 次真实 API，有原始响应和用量。'],
         ['“文本帮助提出正确目标项”','在受限 DSL 与这批受控日志上有证据；路线题的本题日志优于无/错配日志。'],
         ['“比不学习的笨办法稳定更强”','不成立。路线题全报 1 更低，三库澄清版对全报 1 的配对区间均跨零。'],
         ['“自动反馈修一次就更准”','不成立。完整配对结果没有改善案例，存在变坏。'],
         ['“稀疏正则一定带来提升”','没有稳定证据。原提示下 NL4Opt 的有/无正则区间跨零；OptMATH 六个完整配对题全部打平；MAMO 仅一道改善、五道打平。'],
         ['“低遗憾说明价格恢复准确”','被具体反例推翻。必须分开报告参数、结构和决策。'],
         ['“F1 就是隐式约束找回率”','不能这样写。本轮 F1 只针对目标中的线性项/软惩罚表达式。'],
         ['“全矩阵逆优化对照已经做过”','不能这样写。完整库只有预声明监测项，而且知道设计门槛和隐藏成本符号。'],
         ['“已经恢复真实老师傅的排班经验”','没有。三库小规模公开题＋合成软惩罚、日志、历史；未用真实排班或真实人工决策。'],
         ['“符合最新理论的有限样本保证”','没有。本轮的盒约束、噪声、次梯度预算与引用论文假设不同。'],
         ['“已经够 CCF A 投稿”','没有。尚缺新的确认集、独立模型/日志来源、更多生成重复与真实业务验证。']])+'''
<p>更早的纯本地压力测试仍然可用于数学模块检查；它们不能当作 LLM 文本理解能力的证据。本轮不覆盖旧报告，也不把原本失败的成绩修成成功。</p>
<p>公开题目也可能已进入模型训练资料，本轮无法排除这种污染；没有使用私有新题来验证迁移。API 返回的模型名不是可离线锁定的权重版本。</p>
<p>本轮把“文本 → 公式 → 数学估计 → 新场景检验”的链路跑通并找到了可复查的错误机制。下一阶段的研究问题应收窄为：怎样让 LLM 给出可检查的符号与成本语义，并用训练证据拒绝错模型；还不能先许诺普遍优越。</p></section>''')
    refrows=[[esc(r['title']),link(r['url'],'原文'),esc(r['usedFor'])] for r in refs['items']]
    body.append('''<section id="evidence"><h2>论文依据、复算材料与检查范围</h2>
<p>文献用于明确方法出处和限制，没有把几篇论文的名字拼起来当作已证明的创新。此次为定向检索，不是系统综述。未沿用未经核实的 2026 年论文理论主张。</p>'''+
        table(['论文或资料','来源','这轮实际用了什么'],refrows)+f'''
<p>数学测试：6 项原始测试＋3 项稀疏割修复测试通过。原始批次审计 {a['verificationAssertions']:,} 条断言通过，检查冻结哈希、API 输入键隔离、噪声界、决策可行/整数性和逐项计分。键检查不等于证明整个自然语言里绝无信息泄漏；发送内容也保存在原始请求中。</p>
<p>独立求解交叉核验覆盖每题 seed=19 的第 0 个增强上下文：12 个连续题用二维顶点/折线交点枚举，7 个巡回题用独立 MTZ 模型，6 个配餐题用整数网格枚举，共 25 个通过。另 2 个配餐题超过 250,000 点枚举上限，明确标为未独立枚举。交叉检查共享源题解释，并不是独立人工重建全部 27 题。</p>
<ul><li>{link('all-results.json','全部结果与每个测试方案')}；{link('all-results.csv','轻量 CSV')}；{link('analysis.json','完整汇总与配对结果')}。</li>
<li>{link('protocol.json','原始方案')}；{link('design-amendment.json','K=10 变更')}；{link('feedback-repair-amendment.json','反馈失败处理修订')}；{link('clarified-prompt-addendum.json','提示澄清追加方案')}。</li>
<li>{link('source-audit.json','全部候选与排除原因')}；{link('freeze.json','输入哈希')}；{link('execution-code-freeze.json','运行时代码哈希')}。</li>
<li>{link('verification.json','计分检查')}；{link('independent-checks.json','独立求解检查')}；{link('solver-repair-checks.json','工程修复诊断')}；{link('mechanism-diagnostics.json','符号干预与特征激活')}。</li>
<li>{link('REPRODUCE.txt','复算说明')}；{link('verify_bundle.py','离线证据核验程序')}；{link('CHECKSUMS.json','全部文件校验清单')}；{link('DATA-LICENSE.txt','来源与许可')}。</li></ul>
<p class="note">原始 token 记录只用于估算 API 费用。所有图从保存的原始行生成，图片配套 SVG 与画图元数据。数据包只含公开来源与本轮研究产物，不含账户密钥或个人聊天。</p></section>''')
    css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f4f3ee;color:#162a31;font:16px/1.8 "Microsoft YaHei",system-ui,sans-serif}main{max-width:1440px;margin:auto;padding:32px}header{padding:40px;background:#123e47;color:#fff;border-radius:16px}h1{font-size:clamp(28px,4vw,52px);line-height:1.3;margin:16px 0}h2{font-size:27px;margin:0 0 20px}h3{font-size:21px;margin-top:30px}.eyebrow{color:#b9dcd6;letter-spacing:.05em}.lead{font-size:19px;max-width:940px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:30px}.cards>div{background:#20515a;padding:18px;border-radius:8px;font-size:14px}.cards strong{display:block;font-size:29px;color:#ffe4ac}.verdict{background:#e6f0ed;border-left:5px solid #087c6d;padding:20px}.verdict strong{font-size:21px}section{background:white;padding:34px;margin:25px 0;border-radius:12px;scroll-margin-top:20px}nav{display:flex;flex-wrap:wrap;gap:8px 20px;padding:22px 0}a{color:#006a83;text-underline-offset:3px}nav a{font-weight:600}p{margin:15px 0}li{margin:12px 0}code{font:14px/1.7 Consolas,monospace;background:#f0f3f3;padding:2px 5px;overflow-wrap:anywhere}.scroll{overflow-x:auto;margin:20px 0;border:1px solid #dce4e4;border-radius:6px}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.6}th,td{text-align:left;vertical-align:top;padding:11px 13px;border-bottom:1px solid #e5e9e9}th{background:#eaf1f0;white-space:nowrap}td{min-width:70px}tr:nth-child(even){background:#fafbf9}figure{margin:28px 0;padding:15px;border:1px solid #dee6e5;background:#fff}figure img{display:block;width:100%;height:auto}figcaption,.note{font-size:14px;color:#455e64}.formula{font:16px/2 Consolas,"Microsoft YaHei",sans-serif;background:#f5f3e9;padding:20px;border-left:4px solid #b18431;overflow-x:auto}.plain{background:#fff7e5;padding:16px}.scroll:focus,summary:focus,a:focus{outline:3px solid #bd6200}summary{cursor:pointer;font-weight:bold;padding:12px}footer{padding:25px 0;font-size:14px;color:#4a5a60}@media(max-width:700px){main{padding:12px}header,section{padding:20px}.cards{grid-template-columns:repeat(2,1fr)}.cards strong{font-size:23px}figure{padding:5px}h2{font-size:24px}li{margin:14px 0}nav{gap:10px}table{font-size:12px}}@media print{body{background:white}main{padding:0;max-width:none}nav{display:none}section{break-before:auto;border:0}figure{break-inside:avoid}.scroll{overflow:visible}details{display:block}header{background:#fff;color:#163b44}.cards>div{background:#edf2f0;color:#163b44}.cards strong{color:#163b44}a{color:inherit}}'''
    doc='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeepSeek 文本闭环实验 · 完整研究报告</title><style>'+css+'</style></head><body><main>'+''.join(body)+'<footer>批次：deepseek-grounding-20261020-v1 · 软件版本保持 0.1.0 · 独立保留原始、追加、修复三类证据。</footer></main></body></html>'
    (OUT/'完整研究报告.html').write_text(doc,encoding='utf8')
    (OUT/'实在结论.txt').write_text('''DeepSeek 文本闭环实验｜2026-10-20｜软件 0.1.0

这回真的让 DeepSeek 干活了：397 次真实 API，三套公开题目，27 题准入，16 种办法。
模型写日志、读日志给公式、直接猜参数、接收训练反馈改公式；原始调用都在 llm/raw。
日志、软惩罚和历史是受控合成的，不是老师傅真实排班记录。

有用的地方：
路线题澄清提示组，本题日志遗憾 3.499%，没有日志 21.075%。
但“全报 1”只有 1.196%，所以还不能说我们稳定打败笨办法。

翻车的地方：
MAMO 澄清组完成 15/16，成功部分平均遗憾 290.839%，完整均值缺失。
DeepSeek 曾把苹果的成本写成负号，最终算成免费：一个场景真实花费 75，最优仅 2.4394。
反馈修改能把一些模型修到能跑，却没有在完整配对题中带来决策改善。
还有决策遗憾 0.895% 但参数误差 246.978% 的例子，不能只看方案分数就夸价格学准了。

记账：
2,912 行计划结果：2,707 完成，101 方法失败，104 因一道来源题未准入而阻断。
5 个求解接口错误另做修复复查，全通过；原表失败没有涂掉。
token 估算 API 费用约 0.66–1.31 元，非实际账户发票。其他资源和失败都在完整报告。

先打开 完整研究报告.html。全部原始结果、提示、公式、图表、逐题数据、来源许可和复算程序都在同一目录。
结论：LLM 已真实接上，文本有局部作用；普遍优越、准确恢复价格、自动反馈必然改进，都没有成立。
''',encoding='utf8')
    print('report generated',len(doc),'characters; five figures; tables')

if __name__=='__main__':main()
