"""Evidence-first Chinese report; all numerical claims derive from checked records."""
import html,json,os,statistics as st,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=Path(os.environ.get('STRESS_OUT',str(ROOT/'outputs/inverse/public-stress-20261020-v2')))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'work/research/mplconfig'));sys.path.insert(0,str(ROOT/'work/research/plot-deps'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
LABEL={'zero':'全报零','unit':'报已知价格中位数','midpoint':'固定报上界一半','random':'固定种子随机报数','text_l1':'文本候选＋稀疏逆优化','text_no_l1':'同候选、不加稀疏','full_l1':'全部候选＋稀疏','center':'逆优化后尽量靠近常识价','subgradient':'50 步投影次梯度'}
EN=['Zero','Known-price median','Midpoint','Random','Text + L1','Text, no L1','Full bank + L1','Prior center','Subgradient']
FAM={'NETLIB':'NETLIB 连续规划','ORLIB':'OR-Library 背包','TSPLIB':'TSPLIB 路线'}
def read(n):return json.loads((OUT/n).read_text(encoding='utf8'))
def pct(v):return '未完整算出' if v is None else f'{100*v:.3f}%'
def num(v):return '—' if v is None else f'{v:.5g}'
def table(head,rows):
 return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table></div>'
def main():
 source_manifest=ROOT/'datasets/stress-public-v1/download-manifest.json'
 if source_manifest.exists():shutil.copy2(source_manifest,OUT/'download-manifest.json')
 a=read('analysis.json');cfg=read('protocol.json');audit=read('source-audit.json');v=read('verification.json');mech=read('mechanisms.json');cross=read('independent-checks.json');rows=read('all-results.json');control=read('additional-control.json')
 ss=[r for r in a['summaries'] if r['K']==10 and r['noise']==.1];res=a['resources'];methods=cfg['methods']
 sources=sum(r['status']=='admitted' for r in audit);status=a['statusCounts'];diagnostic=len(a['diagnosticFailures'])
 plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
 chinese=Path('C:/Windows/Fonts/msyh.ttc').exists()
 if chinese:
  font_manager.fontManager.addfont('C:/Windows/Fonts/msyh.ttc')
  plt.rcParams['font.family']=font_manager.FontProperties(fname='C:/Windows/Fonts/msyh.ttc').get_name()
  plt.rcParams['axes.unicode_minus']=False
 fig,axs=plt.subplots(1,3,figsize=(17,6),layout='constrained')
 for ax,f in zip(axs,FAM):
  data=[next(r for r in ss if r['family']==f and r['method']==m) for m in methods]
  for i,r in enumerate(data):
   if r['fullCohortMean'] is not None:
    ax.barh(i,r['fullCohortMean']*100,color='#21828a' if r['method']=='text_l1' else '#7b8d9f')
    ax.text(r['fullCohortMean']*100+.01,i,f'{r["fullCohortMean"]*100:.2f}',va='center',fontsize=9)
   else:ax.text(.01,i,f'未完整算出（缺 {r["failedRuns"]} 次）' if chinese else f'INCOMPLETE ({r["failedRuns"]} failed runs)',color='#a64035',va='center',fontsize=8)
  ax.set_yticks(range(len(methods)),[LABEL[m] for m in methods] if chinese else EN);ax.invert_yaxis();ax.set_title(f'{f}：{data[0]["admittedSources"]} 题 × 3 次重复' if chinese else f'{f}: {data[0]["admittedSources"]} sources x 3 seeds');ax.set_xlabel('完整队列平均费用损失（%）' if chinese else 'Complete-cohort mean regret (%)')
  finite=[r['fullCohortMean']*100 for r in data if r['fullCohortMean'] is not None]
  maximum=max(max(finite),1e-6) if finite else 1;ax.set_xlim(0,maximum*1.25);ax.set_ylim(len(methods)-.5,-.5);ax.grid(axis='x',alpha=.15)
 fig.suptitle('九种方法全部展示｜10 份历史，费用差上限 10%｜没算完，不填零' if chinese else 'All nine methods | K=10, cost-gap cap=10% | incomplete results are not zero',fontsize=15)
 fig.savefig(OUT/'primary-results.png',dpi=180);plt.close(fig)
 fig,axs=plt.subplots(1,3,figsize=(16,5),layout='constrained')
 for ax,f in zip(axs,FAM):
  rr=[r for r in rows if r['family']==f and r['method']=='text_l1' and r['K']==10 and r['noise']==.1 and r['status']=='complete']
  ax.scatter([r['relativeMAE']*100 for r in rr],[r['meanRegret']*100 for r in rr],color='#21828a',s=30)
  selected=[]
  if rr:
   selected=[max(rr,key=lambda r:r['meanRegret']),max(rr,key=lambda r:r['relativeMAE'])]
   low=[r for r in rr if r['meanRegret']<=.01]
   if low:selected.append(max(low,key=lambda r:r['relativeMAE']))
  used=set()
  for r in selected:
   key=(r['id'],r['seed'])
   if key in used:continue
   used.add(key);ax.annotate(r['id']+'/'+str(r['seed']),(r['relativeMAE']*100,r['meanRegret']*100),fontsize=8,xytext=(-4,5),textcoords='offset points',ha='right')
  ax.set_xlabel('隐藏价格相对误差（%）' if chinese else 'Hidden-price relative MAE (%)');ax.set_ylabel('费用损失（%）' if chinese else 'Decision regret (%)');ax.set_title(f'{f}：本方法全部已完成运行' if chinese else f'{f}: every completed text + L1 run');ax.grid(alpha=.2)
 fig.suptitle('全部点保留；仅标注最大损失、最大价格误差、低损失高误差样本' if chinese else 'All points retained; labels mark largest regret, largest price error, and low-regret/high-error cases',fontsize=14)
 fig.savefig(OUT/'price-versus-decision.png',dpi=180);plt.close(fig)
 conclusions=[]
 for f in FAM:
  t=next(r for r in ss if r['family']==f and r['method']=='text_l1');u=next(r for r in ss if r['family']==f and r['method']=='unit')
  c=next(r for r in a['comparisons'] if r['family']==f and r['K']==10 and r['noise']==.1 and r['reference']=='unit')
  if c['n']:
   evidence=f'按题比较赢／平／输为 {c["wins"]}/{c["ties"]}/{c["losses"]}；均差区间 [{100*c["ci95"][0]:+.3f}, {100*c["ci95"][1]:+.3f}] 个百分点。'
  else:evidence='没有足够的完整配对，不能比较胜负。'
  conclusions.append(f'{FAM[f]}：本方法平均费用损失 {pct(t["fullCohortMean"])}，不看历史、直接报已知价格中位数为 {pct(u["fullCohortMean"])}。'+evidence)
  if t['failedRuns']==0:conclusions.append(f'{FAM[f]}的隐藏价格平均相对误差仍为 {pct(t["meanRelativeMAEOnSuccessful"])}。决策表现和价格恢复必须分别看。')
 afro=[x for x in mech['afiroChecks'] if x['noise']==.1 and x['status']=='complete'];afro19=next((x for x in afro if x['seed']==19),None)
 afrot=next((x for x in afro19['methodResults'] if x['method']=='text_l1'),None) if afro19 else None
 if afrot:
  conclusions.append(f'AFIRO／种子19：两个真价为 {", ".join(num(x) for x in afro19["truth"][:2])}，学成 {", ".join(num(x) for x in afrot["theta"][:2])}。价格相对误差 {pct(afrot["relativeMAE"])}，测试费用损失却是 {pct(afrot["meanRegret"])}。这是“高分不等于算对账”的直接反例。')
  lossfinding='报零反而得到了更低的训练损失，当前拟合目标在这些生成历史上确实奖励了错误价格。' if afro19['zeroLoss']+1e-8<afro19['truthLoss'] else '这两个损失的比较没有证明报零更好。'
  conclusions.append(f'在同一批含噪历史上，真价的训练损失为 {num(afro19["truthLoss"])}，报零为 {num(afro19["zeroLoss"])}。'+lossfinding+'不能一概甩锅给求解器或稀疏项。')
  geo=afro19['objectiveDifferenceOverFeasibleSet']
  conclusions.append(f'这也不只是“测试根本没用到那两项”：AFIRO 的 10 个测试最优方案中，两项分别出现 {geo["testOracleActivationCounts"][0]} 次和 {geo["testOracleActivationCounts"][1]} 次。价格参与了账单，仍不等于历史方案能唯一说明价格。')
  clean=next((x for x in mech['afiroChecks'] if x['seed']==19 and x['noise']==0 and x['status']=='complete'),None)
  if clean:
   unreg=next(x for x in clean['methodResults'] if x['method']=='text_no_l1')
   conclusions.append(f'同题同种子、无噪声且不加稀疏时，价格相对误差仍为 {pct(unreg["relativeMAE"])}，决策损失为 {pct(unreg["meanRegret"])}。无噪声的参数范围为 '+', '.join(f'[{num(b["lower"])}, {num(b["upper"])}]' for b in clean['profile']['bounds'])+'；这直接检查了历史信息够不够，不能把所有错误都归因于噪声。')
 conclusions.append(f'有 {diagnostic} 个最优面诊断没有得到有限、认证的答案，具体超时或无界原因逐项保留；不能把它们当成“最坏也没事”。')
 blocked=[r for r in a['failures'] if 'history generation' in str(r.get('error',''))]
 if blocked:conclusions.append(f'{len(blocked)} 条主记录被历史生成失败连带阻断。其中连不需要历史的固定报数基线也被同一个入口拦住，这是管线缺陷，不能归为各算法独立失败。原失败不删除，完整队列均分不强行补出来。')
 conclusions.append('本轮不能证明自由文本理解有效：文本是知道真实结构的受控模板，数学方法是在这份提示下比较。也不能证明已恢复隐式约束：这次只遮蔽目标系数，约束完整给出。')
 conclusions.append('每题只遮两项费用，其余成本和约束已知。低决策损失可能主要来自原本就给全的大部分模型，不能写成“从残缺日志恢复了整个真实模型”。')
 conclusions.append('本轮不能把“稀疏惩罚带来稳定增益”或“文本候选筛选带来稳定增益”当成已证实卖点。背包相对常见价格和随机报数有改善证据，但相对固定报上界一半的对照，探索区间仍跨零；尚未证明能稳定赢过每一种笨办法。')
 conclusion_text='\n\n'.join(conclusions)
 table1=table(['数据集','方法','完成／应跑','完整队列平均损失','成功部分均值＊','最好／中间／最差（成功运行）','价格相对误差＊','最坏最优面均值'],
  [[FAM[r['family']],LABEL[r['method']],f'{r["completeRuns"]}/{r["scheduledEligible"]}',pct(r['fullCohortMean']),pct(r['successfulOnlyMean']),' / '.join(pct(r[k]) for k in ['minimumRun','medianRun','maximumRun']),pct(r['meanRelativeMAEOnSuccessful']),pct(r['worstFullMean'])] for r in ss])
 contrasts=[c for c in a['comparisons'] if c['K']==10 and c['noise']==.1]
 ct=table(['数据集','本方法减对照','配对题数','均差（百分点）','探索区间','赢／平／输','不完整而未配对的题'],
  [[FAM[c['family']],LABEL[c['reference']],c['n'],num(100*c['meanDifference']) if c['n'] else '—',str([round(x*100,3) for x in c['ci95']]) if c['n'] else '—',f'{c["wins"]}/{c["ties"]}/{c["losses"]}' if c['n'] else '—',','.join(c.get('omittedIncompleteIds',[]))] for c in contrasts])
 source_rows=[]
 for r in a['sourceSummaries']:
  if r['method']=='text_l1' and r['K']==10 and r['noise']==.1:
   u=next(x for x in a['sourceSummaries'] if (x['id'],x['K'],x['noise'],x['method'])==(r['id'],10,.1,'unit'))
   source_rows.append([r['id'],f'{r["completed"]}/3',pct(r['minimum']),pct(r['median']),pct(r['maximum']),pct(r['mean']),pct(u['mean'])])
 source_table=table(['题','完成重复','本方法最好','中间','最差','本方法平均','常见价格平均'],source_rows)
 control_table=table(['数据集','完成／应跑','三候选全部报常见价：完整均值','与本方法的完整配对题数','本方法减此对照（百分点）','探索区间'],[
  [FAM[r['family']],f'{r["complete"]}/{r["scheduled"]}',pct(r['fullCohortMean']),len(r['pairedSourceIds']),num(100*r['textMinusConstantMean']) if r['textMinusConstantMean'] is not None else '—',str([round(100*x,3) for x in r['ci95']]) if r['ci95'] else '—'] for r in control['summary']])
 prof=[]
 for p in a['profiles']:
  if p['status']=='complete':
   for b in p['bounds']:prof.append([p['id'],p['seed'],b['parameter']+1,num(b['truth']),f'[{num(b["lower"])}, {num(b["upper"])}]', '到达人为上界' if b['hitsDeclaredUpper'] else '未到上界','是' if b['containsTruth'] else '否'])
  else:prof.append([p['id'],p['seed'],'—','—','诊断失败','—',p.get('error')])
 mt=[]
 for r in mech['afiroChecks']:
  if r['status']=='complete':mt.append([r['seed'],r['noise'],num(r['truthLoss']),num(r['zeroLoss']),num(r['minimumLoss']),'; '.join(f'[{num(b["lower"])},{num(b["upper"])}]' for b in r['profile']['bounds'])])
 old=mech['historicalMamoWitness']
 face_table=table(['题','种子','测试情境','默认方案损失','同一估计最优面中的最坏损失','两方案L1距离'],[
  [r['id'],r['seed'],r['context'],pct(r['regret']),pct(r['worstRegret']),num(r['worstDistanceL1'])] for r in a['largestFaceGaps'][:5]])
 oldparagraph=f'保留的旧 MAMO 第 44 题证据：模型给两个方案都算 {old.get("predictedDefault","—")}；真实费用分别为 {old.get("trueDefault","—")} 和 {old.get("trueWorstExact","—")}。漏价被估成零后，多调运余货在模型里免费，真实世界却收钱。它是旧案例，单列解释，没混进本轮均分。'
 failure_table=table(['ID','种子','K','噪声','方法','状态','原因'],[[r['id'],r['seed'],r['K'],r['noise'],LABEL[r['method']],r['status'],r.get('error') or str(r['testErrors'])[:240]] for r in a['failures']])
 df=table(['ID','种子','方法','测试上下文','方向','原因'],[[r['id'],r['seed'],LABEL[r['method']],r['context'],r['side'],r['error']] for r in a['diagnosticFailures']])
 audit_table=table(['数据集','题','状态','原题最优值','公开值','原因'],[[r['family'],r['id'],r['status'],r.get('originalObjective','—'),r.get('publishedOptimum','—'),r.get('error','一致')] for r in audit])
 resources=f'''记录到的有效主运行墙钟至少 {res['wallSeconds']/60:.2f} 分钟；最终完成工作进程 CPU 合计 {res['completedWorkerCPUSeconds']/60:.2f} 分钟，全部尝试的 CPU 记录完整：{res['CPUCompleteness']}。首次 v2 中断的检查点另记录 CPU 至少 {res['interruptedCheckpointCPUSeconds']/60:.2f} 分钟；重复调度和未写入检查点的消耗不明，不能用此表声称总成本。正式调度 3 个并行工作进程，单个进程最大峰值内存 {res['peakWorkerRSSBytes']/1024**2:.1f} MiB。最终任务前向调用 {res['forwardCalls']:,} 次，求解器累计运行 {res['solverSeconds']/60:.2f} 分钟。独立核验另外用墙钟 {cross['wallSeconds']:.2f} 秒、CPU {cross['cpuSeconds']:.2f} 秒；机制检查另外用墙钟 {mech['wallSeconds']:.2f} 秒、CPU {mech['cpuSeconds']:.2f} 秒。累计 CPU 可以大于墙钟时间，二者不能相加。峰值内存不是整台机器同时占用的总内存。付费 API 调用 0，API 费用 0 元；电量未测。'''
 resources+=f' 最终运行中未正常收尾的工作进程，已保存行的 CPU 另外至少 {res["unfinishedWorkerCheckpointCPUSeconds"]/60:.2f} 分钟。'
 incident_note='本次运行未记录重复调度事故；原发布版本的事故和修复经过见原证据包。'
 if res.get('overlappingResumeIncident'):
  incident_note='首次 v1 因中文绝对路径读取问题中止，92 条部分记录和修复前代码保存在 interrupted-v1，不与正式 v2 混算。随后执行会话中断；恢复时普通权限未看到后台进程，误启动了第二个调度器。发现后停止两者，把全部受影响任务放入 overlapping-resume-discarded，从原冻结输入重新计算；最早已完成的 13 个任务原样保留。现已加独占锁。这些是实现与调度失误，不是基准题或算法失败。中断和重复运行的全部 CPU 无法补算，不能假装成零。'
 correction_note='<p>旧恢复记录曾错误标注“进程全部消失”，原记录仍保留；事实更正见 <a href="incident-corrections.json">执行事故更正单</a>。快照目录数量不能当成真实故障次数。</p>' if (OUT/'incident-corrections.json').exists() else ''
 sections=f'''<header><small>LLM4ORTT 0.1 · 多公开基准压力测试 · 2026-10-20</small><h1>分数好，不代表账算对</h1><p>三个基准库；14 道预列候选，{sources} 道可用；3 次重复、9 种方法、2 个历史数量、2 个噪声上限。共登记 {a['schedule']:,} 条排程，失败与未执行都在账上。</p></header>
<nav><a href="#verdict">实在结论</a><a href="#scores">全部对照</a><a href="#case">逐题查账</a><a href="#mechanism">毛病根子</a><a href="#failures">翻车与消耗</a><a href="all-results.csv">完整 CSV</a></nav>
<section id="verdict"><h2>这一轮到底说明了什么</h2>{''.join('<p>'+html.escape(c)+'</p>' for c in conclusions)}
<p><b>该收回的想法：</b>“只要决策分高就恢复了真实价格”“误差都能靠加稀疏解决”“换了几个题就能宣布普遍有效”。本轮每个库都只是小样本，结果可以支持排查方向，不能支持大范围保证。</p></section>
<section id="scores"><h2>九种方法都摊开</h2><p>主条件固定为 10 份历史、10% 费用差上限。价格以可见价格的中位数换算单位，所以“报 1”就是报已知价格中位数；没有使用被遮住的真价来定换算比例。随机方法每题每种子只抽一次，没挑最好的一次。真价超过预定上界的情况也保留。</p>
<img src="primary-results.png" alt="三个基准库的全部九种方法；不完整结果明确标出">{table1}<p>＊成功部分均值和价格误差只描述算完的记录，不能替代完整队列均值。任何一次缺失，该方法的完整均值就显示“未完整算出”。“最好／中间／最差”来自题×种子的运行分数，不是置信区间。原始费用遗憾公式为 max(0,真实费用−真最优费用)/max(1,|真最优费用|)，再对 10 个测试情境平均。</p>
<h3>每块地重复三次，好坏都记</h3>{source_table}<p>任何一次没完成，该题的完整汇总显示“未完整算出”，原始已完成记录仍可在下面查到。</p>
<h3>是否真的比笨办法强</h3>{ct}<p>负数表示本方法较好。每题先平均 3 次种子，再以原题为单位做 5,000 次配对 bootstrap。未做多重比较校正，区间仅作探索；NETLIB 只有两个可用题，尤其不能把区间当成普遍保证。不完整的配对题号明确列出。</p>
<p>四个不学习对照给“明确遗漏的两项”报数，其余候选报零。它们利用了受控模板的结构提示，是“不看历史”，并非“什么都不知道”；这是有结构帮助的强对照。模板本身明确区分“原费用遗漏”和“可能另有附加费用”。</p>
<h3>补充检查：连这种结构区别也不利用</h3><p>另加一个“三个候选都报常见价格”的笨对照。先写 <a href="control-addendum.json">补充规格</a>，再对全部 39 个原题×种子计算；同一测试输入和记分公式，不进入原九方法排程，也不替换失败。它完全不读历史，因此不受历史生成入口阻断。下表是事后探索，不能冒充预先设定的主比较。</p>{control_table}<p>逐方案、错误和资源见 <a href="additional-control.json">附加对照记录</a>。另外用墙钟 {control['wallSeconds']:.2f} 秒、CPU {control['cpuSeconds']:.2f} 秒。配对不完整的来源仍不参加配对均差，不能据此推断整个队列胜负。</p>
<p>“文本＋稀疏”与“同候选、不加稀疏”只改变惩罚；与“全部候选＋稀疏”只改变候选范围。这两项才是本轮对应的控制比较。全部候选也只有 5 项，不叫全矩阵逆优化。</p></section>
<section id="case"><h2>每道题、每次重复，自己能对账</h2><label>题 <select id="source">{''.join(f'<option value="{r["id"]}">{r["family"]} / {r["id"]}</option>' for r in audit if r['status']=='admitted')}</select></label>
<label>种子 <select id="seed"><option>19</option><option>43</option><option>67</option></select></label><label>历史数 <select id="k"><option>10</option><option>5</option></select></label><label>噪声上限 <select id="noise"><option value="0.1">10%</option><option value="0">0%</option></select></label><div id="case-data"></div>
<p>所有训练、测试情境和逐个方案都在 <a href="all-results.json">原始结果 JSON</a>；输入、真价和被遮位置保存在 inputs 文件夹。CSV 便于筛选，JSON 保留完整方案。</p></section>
<section id="mechanism"><h2>两种“账不对”要分开</h2><h3>一、做对方案，不等于猜对价格</h3><img src="price-versus-decision.png" alt="价格误差与费用损失的逐次散点，含低损失高误差反例">
<p>历史告诉我们的通常是“甲方案不比乙方案差”，不是“这个价格等于几块钱”。很多价格都能让同一方案获胜；有的费用项又几乎不参与测试。盲报一个常见价格也可能拿高分，所以必须和不看历史的办法比。</p>
<h3>二、带噪声时，拟合目标可能偏爱错误价格</h3>{table(['AFIRO种子','噪声上限','真价训练损失','报零训练损失','最小训练损失','两个参数的近最小损失范围'],mt)}
<p>系统优化的是“怎样让历史方案看起来少吃亏”。把某些价格压到零，历史选择的损失在这本账上就变小了。在 AFIRO 的三个种子里，真价格得到的训练损失反而更高；不加稀疏也存在同样问题。这说明要检查拟合目标与数据生成方式是否合适，不能仅凭求解器报告“最优”就说学到了真价格。</p>
<p>这张表是发现 AFIRO 反例后的机制检查，复用了全部三次冻结样本，未改变主成绩。比较无噪声和含噪声两行，可以看出是“本来信息就不够”，还是“为了迁就错误决策，把价格压错了”。如果不加稀疏也一样错，就不能说全是稀疏的锅。</p>
<h3>三、同样被模型叫作最优，也可能真的差很远</h3><p>{oldparagraph}</p>
{face_table}<p>上表保留新实验中已完成诊断的本方法案例，按“最坏损失减默认损失”由大到小展示前五个；这是事后解释用的见证，不是重选测试集。完整样本仍在均分里。若显示差为零，仅说明该次已认证检查的费用差很小，不代表其他超时案例安全。</p>
<p>新库逐个检查估计最优方案的最好和最坏真实费用，并保留方案之间的距离。算出来差不多就如实报；算不完就报未查明。这里的最好／最坏需要真值，只是查错工具，实际部署不能偷看真值选好方案。</p>
<details><summary>全部参数范围：包括宽范围、错范围、诊断失败</summary>{table(['题','种子','参数','真值','近最小损失范围','上界情况','包含真值？'],prof)}</details>
<p>这些范围是“训练损失接近最小”的解集，不是置信区间。范围窄也未必对：它可能把真值挤出去了。碰到 10 这个上限，只能说触及人为边界，不能说数据识别出了上限。</p>
<details><summary>被遮价格在测试里究竟占多少</summary>{table(['题','种子','两个真价','测试最优方案中隐藏费用绝对占比','始终没用到的隐藏项数','真价越过预定上界？'],[[e['id'],e['seed'],str(e['truth'][:2]),pct(e['testOracleHiddenAbsoluteCostShare']),e['testOracleInactiveHiddenCount'],e['truthOutsideBox']] for e in a['exposure']])}</details></section>
<section id="failures"><h2>翻车、报错、限时，一条不少</h2><p>排程状态：{html.escape(str(status))}。工作进程状态：{html.escape(str(a['executionStatusCounts']))}。最优面共预列 {a['faceChecksScheduled']} 次方向检查：{html.escape(str(a['faceCheckStatusCounts']))}。blocked_source 是同一份来源不可用产生的未执行记录，不能说成这些方法各自求解失败。主预测失败和额外最坏方案诊断失败也分开计数。</p>
<details><summary>全部主运行失败或未执行记录（{len(a['failures'])} 条）</summary>{failure_table}</details>
<details><summary>全部最优面诊断失败／无界（{diagnostic} 条）</summary>{df}</details>
<p>{resources}</p><p>{incident_note} 下载失败与重试见 <a href="download-manifest.json">下载账</a>。</p>{correction_note}
<p>单次前向求解限时 5 秒，逆拟合限时 90 秒，工作进程看门狗 600 秒。超时体现“这个预算内没完成”，不等于数学上无解。没有通过放宽限时替换旧失败结果。</p></section>
<section><h2>来源、成熟算法和可复核材料</h2>{audit_table}
<p>连续模型使用 HiGHS；背包用 0/1 混合整数规划；路线用度约束和 DFJ 子回路割；逆问题用次优性残差与割平面。还加入一个固定 50 步的投影次梯度，不冒充某篇论文的完整复现。参考 <a href="https://pubsonline.informs.org/doi/10.1287/opre.2.4.393">Dantzig–Fulkerson–Johnson（1954）</a>、<a href="https://epubs.siam.org/doi/10.1137/0108053">Kelley（1960）</a>、<a href="https://arxiv.org/abs/1512.05489">非完美信息逆优化</a>、<a href="https://arxiv.org/abs/2109.03920">逆优化综述</a>。</p>
<p>来源：<a href="https://netlib.org/lp/data/readme">NETLIB</a>（MPS 来自固定 HiGHS v1.15.1 镜像）、<a href="https://people.brunel.ac.uk/~mastjjb/jeb/orlib/mknapinfo.html">OR-Library</a>、<a href="https://comopt.ifi.uni-heidelberg.de/software/TSPLIB95/">TSPLIB95</a>。这是三个基准集合里的少量实例，不是三个行业的大规模验证；历史和情境仍是受控生成。</p>
<p>{v['assertions']:,} 项记录核验通过。独立检查采用 IPM、穷举和另一种 MTZ 路线模型，完整状态见 <a href="independent-checks.json">独立核验</a>，包括未独立重算的项。第一道背包题的逆优化范围还与“列举全部可行方案后一次建模”的结果对照。</p>
<p><a href="protocol.json">冻结方案</a> · <a href="freeze.json">冻结哈希</a> · <a href="verification.json">记录核验</a> · <a href="analysis.json">全部统计</a> · <a href="mechanisms.json">机制诊断</a> · <a href="execution-ledger.json">进程与资源账</a> · <a href="实在结论.txt">纯文字结论</a></p></section>'''
 compact=[{k:r.get(k) for k in ['id','family','seed','K','noise','method','status','theta','meanRegret','relativeMAE','trainingLoss','bestMean','worstMean','error']} for r in rows]
 script='''const D=DATA,L=LABEL;function p(v){return v===null||v===undefined?'未完整算出':(100*v).toFixed(3)+'%'}
function draw(){const id=document.querySelector('#source').value,seed=+document.querySelector('#seed').value,K=+document.querySelector('#k').value,noise=+document.querySelector('#noise').value;const rr=D.filter(r=>r.id===id&&r.seed===seed&&r.K===K&&r.noise===noise);
const headers=['方法','状态','价格估计（全部5项）','费用损失','价格相对误差','训练损失','最好最优面','最坏最优面','错误'];document.querySelector('#case-data').innerHTML='<div class="scroll"><table><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr>'+rr.map(r=>'<tr>'+[L[r.method],r.status,r.theta?r.theta.map(x=>x.toFixed(4)).join(', '):'—',p(r.meanRegret),p(r.relativeMAE),r.trainingLoss??'未记录／不拟合',p(r.bestMean),p(r.worstMean),r.error||''].map(v=>'<td>'+String(v).replaceAll('&','&amp;').replaceAll('<','&lt;')+'</td>').join('')+'</tr>').join('')+'</table></div>'}
document.querySelectorAll('select').forEach(x=>x.addEventListener('change',draw));document.querySelector('#source').value='afiro';draw();'''
 script=script.replace('DATA',json.dumps(compact,ensure_ascii=False)).replace('LABEL',json.dumps(LABEL,ensure_ascii=False))
 css='body{font:17px/1.8 system-ui,"Microsoft YaHei",sans-serif;color:#203341;background:#eff3f5;margin:0}header,section,nav{max-width:1300px;margin:22px auto;padding:28px;background:white;border-radius:10px}header{background:#18394c;color:white}h1{font-size:35px}h2{font-size:25px;border-bottom:1px solid #cddbe4;padding-bottom:10px}nav{display:flex;gap:22px;flex-wrap:wrap}a{color:#087b8b}p{overflow-wrap:anywhere}img{width:100%}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px;border-bottom:1px solid #e2e9ed;text-align:left;white-space:nowrap}th{background:#eef3f6}select{padding:8px;margin:6px;max-width:calc(100% - 12px)}summary{cursor:pointer;color:#087b8b;margin:16px 0}@media(max-width:700px){header,section,nav{margin:10px;padding:18px}h1{font-size:26px}}'
 (OUT/'压力测试报告.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>公开基准压力测试：实在结论</title><style>'+css+'</style>'+sections+'<script>'+script+'</script></html>',encoding='utf8')
 (OUT/'实在结论.txt').write_text('公开基准压力测试 · 2026-10-20 · 软件0.1\n\n'+conclusion_text+'\n\n'+oldparagraph+'\n\n资源账\n'+resources+'\n\n限制：小样本、受控文本、生成历史、公开实例选择固定；不能外推为自由文本能力或真实人类行为结论。所有失败、时间限制和未完整结果见同目录报告。\n',encoding='utf8')
 print(json.dumps({'report':str(OUT/'压力测试报告.html'),'scheduled':a['schedule'],'statuses':status}))
if __name__=='__main__':main()
