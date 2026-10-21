"""Render a self-contained Chinese evidence report from frozen results."""
import csv
import html
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'实验/决策契约研究_2026-10-21_01'
def read(name):return json.loads((OUT/name).read_text('utf-8-sig'))
def esc(value):return html.escape(str(value))

def main():
    primary=read('heldout-summary.json');dev=read('development-summary.json');guard=read('semantic-guard-summary.json')
    natural=read('natural-error-audit.json')['splits']['heldout'];review=read('annotation-review.json')
    transfer=read('transfer-summary.json');sensitivity=read('annotation-sensitivity.json')
    scores=read('heldout-scores.json');cases={c['id']:c for c in read('cases.private.json')}
    events=[json.loads(line) for line in (OUT/'calls.jsonl').read_text('utf-8').splitlines()]
    starts=[e for e in events if e['event']=='started'];ends=[e for e in events if e['event']=='finished']
    assert len(starts)==len({e['id'] for e in starts})==300 and len(ends)==300
    cost={'attempted':len(starts),'complete':sum(e['status']=='complete' for e in ends),
          'promptTokens':sum((e.get('usage') or {}).get('prompt_tokens',0) for e in ends),
          'completionTokens':sum((e.get('usage') or {}).get('completion_tokens',0) for e in ends),
          'summedRequestSeconds':round(sum(e['wallMs'] for e in ends)/1000,2),
          'firstUtc':starts[0]['utc'],'lastUtc':ends[-1]['utc'],
          'note':'Concurrent request seconds are summed, not elapsed experiment duration; no money estimate without verified tariff.'}
    if (OUT/'budget-summary.json').exists():
        assert read('budget-summary.json')==cost
    else:
        with (OUT/'budget-summary.json').open('x',encoding='utf-8') as f:json.dump(cost,f,ensure_ascii=False,indent=2)
    rows=[]
    for row in scores:
        rows.append({'id':row['id'],'text':cases[row['id']]['text'],**{a:int(row['arms'][a]['success']) for a in ('A','B','abstract','witness')}})
    with (OUT/'heldout-results.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    p=primary['primary'];lo,hi=[100*x for x in p['pairedBootstrap95']]
    headline='具体反例未提高留出成绩；真正的检查还必须回到原文与标注'
    intro=f'本轮完成{len(starts)}次真实接口请求，保留全部请求、原始响应、失败格式和评分。主实验没有达到预先设定的正结果门槛。工程上已交付精确几何审计、原文百分比检查器、独立求解器交叉核验和离线命令行工具；研究上形成的是可靠性证据，不能据此宣称已具备AAAI正式长文的新颖性或完成真实业务验证。'
    methodrows=''.join(f'<tr><td>{label}</td><td>{primary["scores"][arm]}/60</td><td>{primary["valid"][arm]}/60</td><td>{calls}</td></tr>' for arm,label,calls in [('A','初始模型 A',1),('B','独立提示模型 B',1),('abstract','抽象诊断后修复',3),('witness','抽象诊断 + 具体反例后修复',3)])
    labels={'clear_generated_error':'明确共同生成错误','clear_annotation_issue':'明确标注缺漏','ambiguous_or_undetermined':'解释歧义，保留未决'}
    casehtml=''.join(f'<details><summary>{esc(e["id"])} · {labels[e["classification"]]}</summary><p>{esc(e.get("analysis",e.get("explanation","")))}</p><p>{esc(e["public_text"])}</p><pre>{esc(json.dumps(e,ensure_ascii=False,indent=2))}</pre></details>' for e in review['entries'])
    rowhtml=''.join(f'<tr class="case-row"><td>{esc(r["id"])}</td><td>{esc(r["text"])}</td>'+''.join(f'<td>{r[a]}</td>' for a in ('A','B','abstract','witness'))+'</tr>' for r in rows)
    literature=(OUT/'文献依据.txt').read_text('utf-8')
    linked_literature=re.sub(r'https://[^\s]+',lambda m:'<a href="'+m.group()+'">'+m.group()+'</a>',esc(literature))
    annotation=(OUT/'annotation-review.txt').read_text('utf-8')
    story=(OUT/'机制与贡献边界.txt').read_text('utf-8')
    body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>决策契约研究｜证据与边界</title><style>
:root{{color-scheme:light;font-family:"Microsoft YaHei",system-ui,sans-serif;color:#17232d;background:#f4f6f7}}body{{max-width:1160px;margin:auto;padding:38px 26px}}h1{{font-size:30px;line-height:1.4;max-width:950px}}h2{{font-size:23px;margin-top:42px}}p,li{{line-height:1.85}}.sub{{color:#56636e}}.lead{{font-size:18px}}.banner{{border-left:5px solid #a35d19;padding:14px 22px;background:#fff6e9}}.metrics{{display:flex;gap:30px;flex-wrap:wrap;margin:28px 0}}.metrics strong{{display:block;font-size:29px;color:#0f766e}}.metrics span{{font-size:13px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{border-bottom:1px solid #d9e0e3;padding:11px;text-align:left;vertical-align:top}}th{{background:#e9eff1}}img{{width:100%;background:white}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1f3;padding:18px;font-size:13px;line-height:1.65}}details{{border-bottom:1px solid #d1dadd;padding:14px 0}}summary{{cursor:pointer;font-weight:600}}a{{color:#12656a}}input{{box-sizing:border-box;width:100%;padding:12px;font-size:16px;margin:12px 0}}.scroll{{overflow:auto}}.case-row td:nth-child(2){{min-width:360px;max-width:620px;font-size:13px}}.case-row td:not(:nth-child(2)){{white-space:nowrap}}@media(max-width:700px){{body{{padding:20px 14px}}h1{{font-size:25px}}.metrics{{gap:20px}}}}@media print{{input{{display:none}}details{{break-inside:avoid}}body{{background:white}}}}
</style><body><p class="sub">llm4orTT 0.1.2 · 2026-10-21 · 可复核研究记录</p>
<h1>{headline}</h1><p class="lead">{intro}</p>
<div class="metrics"><div><strong>300 / 300</strong><span>授权范围内的请求总数</span></div><div><strong>44 → 43</strong><span>抽象诊断 → 加具体反例，正确题数 / 60</span></div><div><strong>3 + 2 + 2</strong><span>七个共同不匹配：生成错误 / 标注缺漏 / 歧义</span></div></div>
<div class="banner"><b>主结论：</b>反例臂相对抽象臂为 {100*p['difference']:.2f} 个百分点；95% 配对自助法区间 [{lo:.2f}, {hi:.2f}]；精确双侧配对检验 p={p['pExact']:.2f}。这没有显示反例带来收益，也不能证明反例在所有任务中无用。</div>
<h2>实验究竟比较什么</h2><p>从公开NL4Opt的289题出发，固定二维连续非负变量和有限参考最优值后172题可解析；排除12个此前研究用题，剩160个去重组。按固定规则选12题开发、60题留出。两支路都看到原题、同一变量目录、同一A/B候选和同一抽象关系诊断；只有反例支路多看到最多6个具体分歧点。参考答案始终离线。公开原题是真实公开基准资料，不是企业历史决策记录；变量目录属于额外监督。</p>
<p>每题先生成A和B，再各修复一次，唯一请求共4次；每个修复臂分摊前置候选后成本为3次。模型为接口返回的 deepseek-flash，temperature=0，关闭思考输出。温度为0不等于跨请求保证相同输出。主指标要求可行域和整个最优解集合都与官方参考一致；不是只比较最优数值，也不是完整语义正确性证明。</p>
<div class="scroll"><table><thead><tr><th>方法</th><th>主指标成功</th><th>格式有效</th><th>每题调用成本</th></tr></thead><tbody>{methodrows}</tbody></table></div>
<p>开发集：A为8/12、B为7/12，两修复臂均7/12。留出集12题有具体见证，两修复臂均3/12，互有1次改善和1次损害；没有见证的48题中，抽象臂41题成功，反例臂40题成功。这一额外损失不能解释成具体反例的作用。</p>
<img src="heldout-results.png" alt="60题上A、B、抽象修复、反例修复及探索性原文检查器的成绩，以及配对变化区间"><p class="sub">图中条长表示与官方标注一致的题数；误差线是10,000次配对自助重采样区间。仅一对差异时的自助区间分辨率很低；零对差异时区间退化为零，并不排除总体存在差异，不替代精确配对检验。<a href="heldout-results.csv">逐题CSV</a> · <a href="heldout-results.pdf">图表PDF</a></p>
<h2>可以据实讲出的研究线索</h2><ol><li><b>两个模型一致，仍然可能一起误解原文。</b>A/B双对41题，仅A对1题，仅B对5题，均不符合参考13题。其中7题彼此的可行域和最优面也一致；逐题核对后，只有3题可明确称为共同生成错误。</li><li><b>参考标注本身也需要审计。</b>七题里有2题明确漏标，另2题“三倍”在等式与不等式解释之间不一致。主结果不改写；两处明确漏标的修正只进入独立敏感性结果。</li><li><b>最优数值相同，不能替代模型检查。</b>初始A有7题与参考方向及原始最优值相同，却未通过可行域与最优面指标。这是本批自然生成输出的观察，包含标注争议，不能全部称作真实语义错误。</li></ol>
<p>因此可写的核心问题是：<b>候选比较能发现分歧，却无法自己裁判原文含义；数值检查、候选检查、原文检查、参考标注检查是不同层次。</b>几何原理和检验边界已有前人工作，本轮的增量在公平信息条件下的实测和可追溯反例，不以新名称替代新颖性证明。</p>
<h2>原文检查器与额外迁移实验</h2><p>第一版只根据12题开发集设计，留出集提取覆盖{guard['extracted']}/60；把A从{guard['baselineSuccess']}题改到{guard['guardSuccess']}题，改善1题、损害0题，p=1。它只会读取明确百分比语句，无法匹配时弃权，不宣称全文理解正确。</p>
<p>第二版使用已经看过的旧留出错误扩展模板，故旧60题不再能作为它的独立验证。另从未生成过答案的17道公开比例题中，按固定种子抽11题，用剩余11次调用生成新候选，再零调用修补。模型输出之前冻结检查器，所有11题进入分母；该集合刻意富集百分比题，结果不可推广到一般任务。</p>
<p><b>新11题：初始{transfer['baselineSuccess']}/11，修补后{transfer['guardSuccess']}/11；提取覆盖{transfer['extracted']}/11，实际修改{transfer['changed']}题，p={transfer['paired']['pExact']:.2f}。</b>没有观察到提升。零配对差异导致自助区间退化为零，不能把它解释成总体效应已被精确证明为零。</p>
<h2>标注敏感性与七个具体案例</h2><p>以下审读来自自动分析者的逐项代入，不是外部人类专家裁决。案例按主评分结果挑出，不能据此估计整个数据集的标注错误率。两份修正参考不覆盖原文件。</p><pre>{esc(json.dumps({k:sensitivity[k] for k in ['modified_ids','sensitivity_counts','sensitivity_abstract_vs_witness']},ensure_ascii=False,indent=2))}</pre>{casehtml}
<h2>已交付的工程能力</h2><ul><li>精确有理数二维LP比较：可行域、最优面、目标弱序、有限分歧点；支持无界方向，拒绝未知字段。</li><li>独立HiGHS核验400模型、400模型对、1,600次包含检查、832个精确反例，全部通过；这些随机模型属于程序测试，没有混入真实错误率。</li><li>离线命令行 <code>research/decision_audit_cli.py</code>；收到一致模型时明确返回“未认证语义”，不会误报安全。</li><li>两版保守文本百分比检查器：保留原文位置、变量匹配证据、修改记录和弃权原因。</li><li>预算账本、全部原始响应、冻结协议、版本修订、逐题分数、源码快照和校验清单。</li></ul>
<p>本轮改动集中在research、scripts、tests，没有修改solver或src，也没有将研究探索直接替换为桌面程序的生产算法。旧实验保持原样。本轮检验语言建模入口，尚未检验真实历史行为的逆优化成本恢复。</p>
<h2>通俗解释</h2><p>想象两个人一起做应用题。他们都写了同一个答案，只说明两人的想法一样，不说明两人都懂了题意。现在的几何检查像一位认真代数的老师：能找出“这个方案在甲的公式里能做，在乙的公式里不能做”的例子。但要判断到底谁对，还得回头读题。</p><p>更麻烦的是，答案册也可能漏写条件。所以这次把“同学算错”“答案册漏项”“题目说得不清”分开存证。多算并不自动等于更可靠；每一层检查都要说明自己究竟保证了什么。</p>
<h2>前沿文献依据</h2><pre>{linked_literature}</pre>
<h2>逐题结果</h2><p>1表示通过冻结主指标，0表示未通过。输入题号或英文关键词筛选；完整数据始终保存在CSV。</p><label for="filter">筛选题目</label><input id="filter" placeholder="题号或原题关键词"><div class="scroll"><table><thead><tr><th>题号</th><th>公开原题</th><th>A</th><th>B</th><th>抽象</th><th>反例</th></tr></thead><tbody>{rowhtml}</tbody></table></div>
<h2>证据入口</h2><p><a href="protocol.json">冻结主协议</a> · <a href="transfer-protocol.json">迁移协议</a> · <a href="annotation-review.txt">七题审读</a> · <a href="机制与贡献边界.txt">机制与贡献边界</a> · <a href="论文叙事草稿.txt">论文叙事草稿</a> · <a href="复算入口.txt">离线复算</a> · <a href="budget-summary.json">调用预算</a></p>
<p class="sub">请求{cost['attempted']}次，接口完整返回{cost['complete']}次；输入{cost['promptTokens']:,} tokens，输出{cost['completionTokens']:,} tokens。接口成功不等于JSON有效或模型正确。所有成绩保留原分母。</p>
<script>document.getElementById('filter').addEventListener('input',function(){{let q=this.value.toLowerCase();document.querySelectorAll('.case-row').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))}});</script></body></html>'''
    (OUT/'研究结果.html').write_text(body,encoding='utf-8')
    draft=f'''研究叙事草稿：从模型一致到原文忠实——优化建模修复中的三层验证边界

状态：证据驱动研究稿，尚非可宣称录用潜力或完成新颖性验证的投稿终稿。

摘要
语言模型生成的优化模型可以通过求解器检查，也可能与另一个生成模型给出相同决策，但这不代表它忠实表达原题。我们在公开NL4Opt二维连续线性规划子集中，隔离具体分歧见证相对于相同抽象诊断的增量作用。预先固定12题开发、60题留出，两修复臂使用同一候选对和调用预算，参考答案不进入模型请求。留出上抽象修复44/60、具体见证修复43/60，差值-1.67个百分点，95%配对自助区间[-8.33,3.33]，精确配对p=1，未显示提升。七个候选一致而共同不匹配参考的案例，经逐项审读分为三个生成错误、两个标注缺漏和两个解释歧义。我们交付精确条件审计、原文证据追踪和不可改写的实验链，以区分模型之间的一致、模型对原文的忠实以及参考标注的可靠性。

1. 问题与动机
本轮从既有逆优化流程的语言建模入口切入，不主张已经恢复现实中的隐含成本。独立生成与互相检查的有效性，受共同错误、信息不足及参考误差影响。将数值一致直接解释为语义正确，可能同时漏过共同误译和错误答案册。

2. 与已有工作关系
TACIT提供结构修补和数值校准的相关思路；本研究未获得同等用户覆盖与纠错监督，不宣称复现其完整算法或击败它。Opt-Verifier与Falsification-Based Verification已研究双侧检查和检测边界；EquivaMap研究一般模型等价映射。本文仅处理变量已对齐的二维连续非负LP，不将多面体包含、反例或共识盲区作为首次发现。Conformal Inverse Optimization依赖相应统计假设，本轮没有使用其校准集，因而没有共形覆盖保证。完整官方来源见文献依据.txt。

3. 实现与条件保证
将有限有理约束转为统一半空间，枚举可行顶点与衰退方向；比较双向可行域包含及完整最优面。若有限点或射线在另一模型中违反约束，返回可代入的有限分歧点。二维、非负和变量意义已对齐是范围限制。精确算术保证算式不受浮点阈值影响，但不能保证自然语言解析正确。整个最优面一致也不意味着所有可行方案的偏好排序一致，故另存目标弱序判定。

4. 公平实验与结果
主比较两臂共享原题、变量目录、A/B模型和同一抽象诊断，唯一额外信息为最多6个具体分歧点。失败格式保留分母；不按分歧筛选主测试。A为42/60，B为46/60，抽象为44/60，反例为43/60。具体见证曝光仅12/60，此子组两臂各3题成功、互有1次改善与损害。无见证子组的差异不可作为具体见证机制证据。正结果门槛未通过。

5. 三种不同的错误来源
初始A/B共同不符合参考13题，其中7题可行域和最优面一致。逐题审读确认三种情况：自然生成的比例计算或方向错误；公开标注遗漏明确系数或变量下界；三倍关系在等式与不等式之间解释不一。审读是事后选择且无外部人类盲审，不用于估计数据集总体误标率。两处明确遗漏只在敏感性文件中修正，主报告维持原始结果。

6. 保守原文检查与迁移
开发集固定的第一版比例检查覆盖1/60，修复1题且未损害其它题，不能据此宣称泛化优势。随后利用已看到的错误扩展模板，另做11题未生成过的比例题迁移；该实验是适应性、富集队列探索，不能替代主终点。实际结果：{json.dumps(transfer,ensure_ascii=False)}。

7. 可复核性
400个随机有理LP及独立HiGHS比较用于程序验证，不混入基准错误率。模型请求总数300，上限内无自动重试；记录原始响应、分支顺序、源文件哈希、严格字段修正及离线评分。使用公开题目而非伪造业务日志，明确保留训练污染风险。

8. 结论与投稿边界
当前证据支持一项谨慎的可靠性叙事：明确分歧证据未在本样本改善修复，候选共识和参考一致性都需要原文核对。当前证据不支持稳定性能优势、一般语义保证、真实业务有效性或足够的AAAI新颖性。要形成正式长文，还缺多模型、多任务、独立人工语义裁决与匹配监督的近邻方法比较；这些缺口不能用本轮小样本探索或大量随机程序测试补写为已完成。
'''
    (OUT/'论文叙事草稿.txt').write_text(draft,encoding='utf-8')
    print(json.dumps({'report':'研究结果.html','modelCalls':cost['attempted'],'paperDraft':'论文叙事草稿.txt'},ensure_ascii=False))

if __name__=='__main__':main()
