"""Render saved follow-up evidence; does not change the frozen analysis."""
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "work/plot-dependencies"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

OUT = ROOT / "outputs/followup-20261020"
LABELS = {
    "full_priority": "原完整约束对照",
    "dual_reuse": "上轮候选：逐步约束＋证据复用",
    "full_adaptive_dual": "完整约束＋动态顺序＋证据复用",
    "full_warm_adaptive_dual": "强对照：再加真实热启动",
}


def load(path):
    return json.loads(path.read_text("utf-8"))


def export_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    a = load(OUT / "analysis.json")
    audit = load(OUT / "independent-followup-audit.json")
    frozen = load(OUT / "freeze.json")
    if not audit["allPassed"] or not a["independentAuditPassed"]:
        raise RuntimeError("Final report requires the complete independent audit")
    primary = a["primary"]
    groups = a["comparisonGroups"]
    sgroups = a["sensitivityGroups"]
    p = frozen["protocol"]
    b8 = {r["method"]: r for r in groups if r["budget"] == p["primary_lp_budget"]}
    primary_s = next(r for r in sgroups if r["cap"] == p["primary_sensitivity_cap"])
    reg = load(OUT / "regression/prior-false-safe.json")
    false_safe_examples = []
    primary_transitions = {}
    from fractions import Fraction
    for file in sorted((OUT / "sensitivity/profiles").glob("*.json")):
        row = load(file)
        if row.get("cap") == p["primary_sensitivity_cap"] and row.get("executionStatus") == "complete":
            transition = (row["verification"]["nominal"]["status"], row["verification"]["upper"]["status"])
            primary_transitions[transition] = primary_transitions.get(transition, 0) + 1
        check = row.get("verification", {}).get("upper", {})
        regret = check.get("exactTrueRegretRational")
        if (row.get("executionStatus") == "complete" and check.get("status") == "safe"
                and regret is not None and Fraction(regret) > Fraction(check["thresholdRational"])):
            false_safe_examples.append({
                "caseId": row["caseId"], "cap": row["cap"],
                "nominalStatus": row["verification"]["nominal"]["status"],
                "conditionalWorst": check["exactWorstRegretRational"], "trueRegret": regret,
            })
    effect = primary["pairedDifference"] * 100
    interval = [v * 100 for v in primary["exploratory95Interval"]]
    flat = [{**{k: v for k, v in r.items() if k != "counts"}, **r["counts"]} for r in groups]
    export_csv(OUT / "comparison-summary.csv", flat)
    export_csv(OUT / "paired-effects.csv", primary["instanceDifferences"])
    flat_s = [{**{k: v for k, v in r.items() if k not in ("nominalCounts", "upperCounts")},
               **{"nominal_" + k: v for k, v in r["nominalCounts"].items()},
               **{"upper_" + k: v for k, v in r["upperCounts"].items()}} for r in sgroups]
    export_csv(OUT / "sensitivity-summary.csv", flat_s)
    preprocessing = []
    for phase in ("comparison", "sensitivity"):
        for file in sorted((OUT / phase / "cases").glob("*.json")):
            case = load(file)
            preprocessing.append({"caseId": case["id"], "phase": phase,
                                  "generatorMs": case["generatorMs"], **case["preprocessing"]})
    export_csv(OUT / "preprocessing.csv", preprocessing)
    prep_median = statistics.median(r["elapsedMs"] for r in preprocessing if r["phase"] == "comparison")

    font = Path("C:/Windows/Fonts/msyh.ttc")
    font_manager.fontManager.addfont(str(font))
    family = font_manager.FontProperties(fname=str(font)).get_name()
    with plt.rc_context({"font.family": family, "font.size": 10, "axes.unicode_minus": False,
                         "svg.fonttype": "none"}):
        fig, ax = plt.subplots(1, 2, figsize=(12, 5.4))
        fig.subplots_adjust(left=.07, right=.98, bottom=.27, top=.82, wspace=.29)
        for method, color, marker, style in zip(LABELS, ["#777777", "#0072B2", "#D55E00", "#222222"],
                                               ["s", "o", "^", "D"], [":", "-", "--", "-."]):
            rows = sorted((r for r in groups if r["method"] == method), key=lambda r: r["budget"])
            ax[0].plot([r["budget"] for r in rows], [100*r["resolvedFraction"] for r in rows],
                       label=LABELS[method], color=color, marker=marker, linestyle=style, linewidth=1.7)
        ax[0].set_xscale("log", base=2)
        ax[0].set_xticks([2, 8, 32], ["2", "8", "32"])
        ax[0].set(ylim=(0, 103), ylabel="正确明确判断比例（%）", xlabel="最多LP调用次数",
                  title="A  更强计算对照：全部120个场景")
        ax[0].legend(loc="lower right", fontsize=7.5, frameon=False)
        ax[0].grid(axis="y", color="#dddddd")
        bars = [primary_s["nominalCounts"]] + [r["upperCounts"] for r in sgroups]
        n = primary_s["planned"]
        bottom = [0.] * len(bars)
        for key, label, color, hatch in [
            ("safe", "条件安全", "#0072B2", ""),
            ("risk_witness", "发现风险", "#D55E00", "//"),
            ("incompatible", "假设不相容", "#777777", "xx"),
            ("unresolved", "未决", "#DDDDDD", "..")]:
            values = [100*b[key]/n for b in bars]
            ax[1].bar(range(len(bars)), values, bottom=bottom, label=label,
                      color=color, hatch=hatch, edgecolor="white", width=.65)
            bottom = [x+y for x, y in zip(bottom, values)]
        ax[1].set_xticks(range(4), ["原预算 0"] + [f"上限 {r['cap']}" for r in sgroups])
        ax[1].set(ylim=(0, 112), ylabel="全部60个独立题目中的比例（%）",
                  title="B  同一方案的误差上限敏感性")
        false_counts = [primary_s["nominalActualFalseSafe"]] + [r["upperActualFalseSafe"] for r in sgroups]
        for i, count in enumerate(false_counts):
            ax[1].text(i, 104, f"实际超阈值 {count}", ha="center", fontsize=8, color="#9A3412")
        ax[1].legend(loc="upper center", bbox_to_anchor=(.5, -.14), ncol=2, fontsize=8, frameon=False)
        fig.suptitle("新实例上的强对照与误差上限检查", y=.97, fontsize=16)
        fig.text(.07, .15, f"主比较（8次LP）：上轮候选减热启动强对照 = {effect:+.2f}个百分点；95%探索区间 [{interval[0]:+.2f}, {interval[1]:+.2f}]。",
                 fontsize=9)
        fig.text(.07, .105, "A：60个独立题目，每题两种噪声。B：另一批60题，真实模拟误差上限已知为1；各预算是同题重复检查。",
                 fontsize=8)
        fig.text(.07, .06, "“实际超阈值”只计获条件安全却实际超阈值的案例。匹配上限来自合成设定，不能当成程序学出了现实误差。",
                 fontsize=8)
        fig.text(.07, .02, "所有预定项留在分母；条件数学证据独立精确核验。仅二维有限动作合成实验，未运行语言模型比较。",
                 fontsize=8)
        fig.savefig(OUT / "followup.png", dpi=200, facecolor="white")
        fig.savefig(OUT / "followup.svg", facecolor="white")
        plt.close(fig)

    lines = [
        "基于上一轮结果的修补与扩展实验", "2026-10-20｜桌面程序0.1.2", "",
        "一、先说已经做好的内容",
        "保留语言提出成本结构—历史行为约束参数—优化器提出方案—检查方案风险的主线。",
        "软件增加明确声明的较宽误差上限检查；综合结论优先采用这项检查，而不继续突出较紧假设下的安全。",
        "没有提供上限时，明确显示只检查单个预算；不按训练残差猜上限，不默认填0。",
        "保留原预算证书和上限证书、同一方案、完整见证、计算预算与未验证的假设，便于逐项核对。",
        "新增两个强对照：完整历史约束＋动态排序＋全局证据复用，分别冷启动和真实basis热启动。",
        "新增8篇原始论文核查，接续旧6篇；所需其他模型保持未运行状态，指标为null。",
        "修改前完整备份位于archives/before-certification-20261020-214544，共4554文件核验通过。", "",
        "二、算法比较的结果",
        "这是一批新的60个底层题目，每题两种误差条件，共120场景；4方法×3预算，共1440次运行。",
        f"主比较在8次LP：上轮候选{b8['dual_reuse']['resolved']}/120，热启动强对照{b8['full_warm_adaptive_dual']['resolved']}/120。",
        f"实例配对样本均值差{effect:+.2f}个百分点，95%探索bootstrap区间[{interval[0]:+.2f}, {interval[1]:+.2f}]。",
        f"事先规定的候选继续门槛是否满足：{primary['candidatePromotionGateMet']}。",
        "该门槛只涉及继续投入的信号，不证明新颖性，也不承诺会议录用。",
        "上轮候选没有超过本轮更强对照，不能继续按“已验证算法优势”写贡献；区间触及0，也不把反向差异写成确定胜负。",
    ]
    for budget in p["lp_budgets"]:
        lines.append(f"预算{budget}次LP的全部方法：")
        for r in (g for g in groups if g["budget"] == budget):
            lines.append(f"  {LABELS[r['method']]}：明确判断{r['resolved']}/{r['planned']}；"
                         f"耗时中位数{r['medianMs']:.2f}毫秒；平均LP{r['meanLpCalls']:.3f}；"
                         f"safe/risk/unresolved/incompatible={r['counts']['safe']}/{r['counts']['risk_witness']}/"
                         f"{r['counts']['unresolved']}/{r['counts']['incompatible']}。")
    warm = [g for g in groups if g["method"] == "full_warm_adaptive_dual"]
    cold8, warm8 = b8["full_adaptive_dual"], b8["full_warm_adaptive_dual"]
    lines += [
        f"三个预算中实际获接受的basis复用共{sum(g['totalBasisAccepted'] or 0 for g in warm)}次；"
        "逐轮getBasis/setBasis状态和单纯形迭代数保存在原始输出，首次即结束的任务没有被算作复用。",
        "两个新对照都显式使用HiGHS simplex；二者只在模型/basis复用上不同。与旧方法相比还同时改变了完整约束和调度，不能把全部差异归因于热启动。",
        f"主预算下冷、热强对照分别为{cold8['resolved']}/120与{warm8['resolved']}/120；分类成绩相同，不能把分类改善归给热启动。",
        f"主预算下冷、热的总单纯形迭代分别为{cold8['totalSimplexIterations']}与{warm8['totalSimplexIterations']}，"
        f"热启动basis获接受{warm8['totalBasisAccepted']}次；这只是本批次的描述性计算证据。",
        f"公共预处理（含旧点估计）耗时中位数为{prep_median:.2f}毫秒，另计于单方法耗时；记录在preprocessing.csv。",
        "LP次数不等于相同计算成本；总耗时含各方法初始化、验证和证据运算，限制为协作式而非严格实时期限。",
        "本轮没有把任何候选计算方法改成声称更优的软件默认值。", "",
        "三、敏感性检查是否解决了上次发现的问题",
        "另一批60个新独立题目，历史由误差最多1.0的合成机制产生；固定同一候选方案，名义预算为0。",
        "分别声明0.4、1、2三个额外上限，共180个双端点记录、360份条件证书；这些不是180个独立题目。",
    ]
    for r in sgroups:
        lines.append(
            f"上限{r['cap']}：原预算条件安全{r['nominalCounts']['safe']}/60、其中实际超阈值{r['nominalActualFalseSafe']}；"
            f"上限处条件安全{r['upperCounts']['safe']}/60、其中实际超阈值{r['upperActualFalseSafe']}；"
            f"发现风险{r['upperCounts']['risk_witness']}，未决{r['upperCounts']['unresolved']}，不相容{r['upperCounts']['incompatible']}；"
            f"真参数被上限集合排除{r['upperTruthExcluded']}/60。")
    lines += [
        f"主上限1下，原预算的{primary_s['nominalActualFalseSafe']}个假安全案例中，"
        f"{primary_s['nominalFalseSafeNotReleasedAtUpper']}个不再获得跨预算安全结论；"
        f"同时仍有{primary_s['rangeSafe']}/60个方案得到条件保证。",
        "上限1已知覆盖生成器行为误差，这是实验前提，不能改写为“算法自己估出了正确上限”。",
        "这60个新题的原预算未出现实际超阈值放行，所以本轮新样本不能证明实际错误放行率下降。",
        "已知旧反例的回归改善与新样本零事件是两条不同证据，不能合并包装成错误率降低的统计结论。",
        "小于真实行为上限的检查仍可能排除真参数；更大上限也会扩大可能成本范围，使一些方案失去保证。",
        "条件安全数量也可能增加：原来空的相容集合变成非空后，一些任务首次有资格获证；这不违反固定非空集合上最坏后悔单调。",
        f"主上限1的安全来源：{primary_transitions.get(('safe', 'safe'), 0)}个原安全保留，"
        f"{primary_transitions.get(('incompatible', 'safe'), 0)}个原不相容变为安全；"
        f"另有{primary_transitions.get(('safe', 'risk_witness'), 0)}个原安全变为风险。",
        "较紧预算不相容、较宽预算相容可以同时发生；软件保留两条事实，不用宽预算结果擦掉原不相容。",
        "两个端点不能定位精确风险翻转点；数值外界也没有被人为强改为单调。", "",
        "不足上限处的全部实际假安全案例（不得隐去）：",
        *[f"  {r['caseId']}，上限{r['cap']}；原状态{r['nominalStatus']}；声明集合内最坏后悔{r['conditionalWorst']}，真实后悔{r['trueRegret']}，阈值1/4。"
          for r in false_safe_examples],
        "这说明“比原预算更大”不等于“已经足够大”；额外检查仍需要上限依据，不能作为自动真实安全认证。", "",
        "四、已知失败案例的回归修复",
        f"上次assignment3-s20011案例：原结果{reg['result']['decisionCertificate']['status']}；"
        f"上限1处{reg['result']['noiseSensitivity']['upperCertificate']['status']}；"
        f"综合结论{reg['result']['decisionGuidance']['status']}。",
        f"真实模拟后悔为{reg['verification']['nominal']['exactTrueRegretRational']}，阈值为1/4。",
        "此例用来检查已知问题是否得到处理，不计入新独立证据。", "",
        "五、数学依据与没有修好的假设边界",
        "若逐条历史误差预算delta不超过Delta，则U(delta)包含于U(Delta)。",
        "对同一固定方案x，非空集合上的最坏后悔随集合扩大不减。",
        "所以U(Delta)有精确非空见证且其有效风险上界不超过阈值，足以保证所有更紧的非空子集合。",
        "若上限集合出现风险见证，只能说明存在该相容反例，不能断言真实成本一定如此。",
        "预算上限、参数框、特征与可行域本身没有被独立验证。错误的硬约束、遗漏成本、漂移或错参数框仍可破坏真实保证。",
        "文献报告给出的遗漏成本幅度Gamma修正只是带额外假设的推导，本轮没有实现或实验验证该扩展。",
        "训练最小误差只回答模型能否解释历史，不给真实误差上限。没有用自动放大预算掩盖不可辨识问题。", "",
        "六、独立核验、测试与保留的证据",
        f"比较运行保存{a['comparisonSaved']}/{a['comparisonPlanned']}，敏感性记录保存{a['sensitivitySaved']}/{a['sensitivityPlanned']}。",
        f"独立总审计通过：{audit['allPassed']}。核验器重新构造原始可行动作、历史约束和精确有理数多边形。",
        "核验包含上下界、相容见证、非空性、固定方案、逐预算嵌套、坐标范围、计划缺项、输入哈希及冻结源码。",
        "不把错假设下的真实损失超标改名为数学错误；也不把数学检查通过写成现实假设已经成立。",
        "90项Python机制与回归测试通过；旧界面13项、新界面11项语义检查通过。",
        "已打包程序0.1.2的真实REST运行通过，模型调用0次；综合风险、固定方案和服务重启后的证书保存均通过。",
        "没有声称完成可见窗口的像素布局测试。", "",
        "七、文献与贡献定位",
        "新增8篇详见research/noise_sensitivity_prior_work.txt；每篇标明原文阅读章节、限制与实际作用。",
        "TACIT已将LLM结构修补和历史行为校准结合；Variable-sized uncertainty已研究不确定集大小敏感性。",
        "因此，本轮是明确的工程与证据改进；集合包含、敏感性图、对偶复用、热启动都不能单独包装成首次发明。",
        "AAAI正式长文仍是目标，但仍需新的方法贡献、真实语言任务和外部验证，不能把合成数据零条件错误当作顶会创新证明。",
        "研究目标详见research/研究目标与贡献边界_v2.txt。", "",
        "八、其他模型与后续接口",
        "research/deferred_model_protocol.json保存未运行的语言结构、逆拟合、风险检查和TACIT式监督比较条件。",
        "所有未执行指标为null，试验列表为空；没有用当前助手回答代替多模型成绩。",
        "未来模型实验须另冻结模型版本、提示词、独立任务与调用预算，保存失败；TACIT式专家纠正监督须公平匹配。", "",
        "九、复核与恢复",
        "resources\\runtime\\python\\python.exe tools\\audit_followup.py",
        "resources\\runtime\\python\\python.exe research\\analyze_followup.py",
        "独立重跑用research/run_followup.py --phase all --out 新目录；已存在的案例不会被覆盖。",
        "附带Python的隔离路径需通过tools/audit_followup.py启动独立校验；首次路径错误与修复说明保存在audit-invocation-note.txt，冻结校验器未改。",
        "comparison/与sensitivity/保存全部输入、真值（仅评价使用）、结果、见证及轨迹；freeze.json与frozen-source/记录实验前冻结。",
        "regression/保存旧失败回归；comparison-summary.csv、sensitivity-summary.csv和comparison-costs.csv用于复算。",
        "archives/before-certification-20261020-214544/恢复说明.txt说明如何在新文件夹恢复上版。",
        "原0.1与0.1.1存档、两轮旧结果和D:\\scr\\temp result继续保留。", "",
        "十、来源与流程工具",
        "TACIT，2026预印本：https://arxiv.org/abs/2609.38434",
        "Variable-sized uncertainty and inverse problems in robust optimization，2018：https://eprints.lancs.ac.uk/id/eprint/86841/",
        "Inverse Optimization with Noisy Data，2018：https://doi.org/10.1287/opre.2017.1705",
        "其余5篇和完整BibTeX见research/noise_sensitivity_references.bib；不声称穷尽所有近邻。",
        "实验设计、统计分析与科研绘图流程参考：Kassis et al. (2026), Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents.",
        "https://doi.org/10.48550/arXiv.2609.00065；这是工具流程引用，不是本研究算法来源。", "",
        "给用户的大白话",
        "这次主要修好两件事：让对照选手更强；让程序在换一个合理误差假设后重新检查自己的结论。",
        "它会把“原先看起来安全，放宽后发现风险”说在前面，同时把两个答案都留下。",
        "但价目表里漏了一项费用，或者把允许犯错的程度仍然估错，多算一次也不能变成万能保证。",
        "这些边界和不利结果会继续作为研究事实保留。", "",
    ]
    report = OUT / "本轮改进与真实结果.txt"
    report.write_text("\n".join(lines), "utf-8")
    metadata = {
        "matplotlib": matplotlib.__version__, "analysisSha256": hashlib.sha256((OUT / "analysis.json").read_bytes()).hexdigest(),
        "reportSha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        "figure": {"pixels": [2400, 1080], "dpi": 200, "publisherComplianceClaim": False},
        "sources": ["analysis.json", "independent-followup-audit.json", "regression/prior-false-safe.json"],
        "transforms": ["all planned counts kept in denominators", "paired noise conditions averaged by instance",
                       "stacked bars show conditional labels, not validated-real-world safety"],
        "plotRuntimeScope": "Workspace-only html dependency workaround; system Python files not modified",
    }
    (OUT / "report-provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), "utf-8")
    print(str(report))


if __name__ == "__main__":
    main()
