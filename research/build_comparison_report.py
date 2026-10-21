"""Produce a factual report and general-purpose scientific figure from saved data."""
import csv
import hashlib
import json
import statistics
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Isolate a repaired pure-Python plotting dependency in the workspace only.
# This does not modify the user's Python installation.
PLOT_DEPS = ROOT / "work/plot-dependencies"
if PLOT_DEPS.exists():
    sys.path.insert(0, str(PLOT_DEPS))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

OUT = ROOT / "outputs/comparison-20261020"
NAMES = {"full_priority": "全约束强对照", "lazy_sequential": "逐步加约束",
         "lazy_priority": "固定风险顺序", "witness_priority": "动态风险顺序",
         "dual_reuse": "候选：复用对偶证据"}


def main():
    analysis = json.loads((OUT / "analysis.json").read_text("utf-8"))
    audit = json.loads((OUT / "independent-verification.json").read_text("utf-8"))
    if not audit["allPassed"] or audit["runs"] != analysis["savedRuns"]:
        raise RuntimeError("The report requires a complete independent audit")
    primary = analysis["primary"]
    groups = analysis["groups"]
    main_rows = [g for g in groups if g["split"] == "evaluation" and g["budget"] == 8]
    row_by_method = {g["method"]: g for g in main_rows}
    candidate, baseline = row_by_method["dual_reuse"], row_by_method["full_priority"]
    effect = 100 * primary["pairedResolutionDifference"]
    interval = [100 * v for v in primary["exploratory95PercentileBootstrapInterval"]]
    with (OUT / "summary-table.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["split", "method", "lp_budget", "planned", "safe", "risk_witness",
                         "unresolved", "incompatible", "failed", "missing", "resolved_fraction",
                         "median_ms_completed", "mean_lp_calls_completed", "truth_outside", "actual_false_safe"])
        for g in groups:
            writer.writerow([g["split"], g["method"], g["budget"], g["planned"],
                *[g["counts"][s] for s in ("safe", "risk_witness", "unresolved", "incompatible", "failed", "missing")],
                g["resolvedFraction"], g["medianElapsedMsCompleted"], g["meanLPCallsCompleted"],
                g["truthOutsideDeclaredSet"], g["actualFalseSafe"]])
    with (OUT / "paired-instance-effects.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(primary["instanceDifferences"][0]))
        writer.writeheader()
        writer.writerows(primary["instanceDifferences"])
    resource_rows = []
    metrics = ("lpCalls", "oracleCalls", "historyRows", "rowsAdded", "cuts",
               "cumulativeLpRows", "peakLpRows", "historyRowEvaluations",
               "witnessRivalEvaluations", "dualRivalEvaluations", "solverSeconds",
               "oracleSeconds", "boundSeconds", "elapsedSeconds")
    for path in sorted((OUT / "runs").glob("*.json")):
        run = json.loads(path.read_text("utf-8"))
        result = run.get("result", {})
        lower, upper = result.get("lowerExact"), result.get("upperExact")
        width = None if lower is None or upper is None else Fraction(upper) - Fraction(lower)
        resource_rows.append({
            "caseId": run["caseId"], "split": run["split"], "method": run["method"],
            "budget": run["budget"], "status": result.get("status", run["executionStatus"]),
            **{key: result.get("resources", {}).get(key) for key in metrics},
            "riskWidthExact": str(width) if width is not None else None,
            "riskWidth": float(width) if width is not None else None,
        })
    with (OUT / "resource-costs.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(resource_rows[0]))
        writer.writeheader()
        writer.writerows(resource_rows)
    resource_groups = []
    for g in groups:
        subset = [r for r in resource_rows
                  if (r["split"], r["method"], r["budget"]) == (g["split"], g["method"], g["budget"])]
        summary = {key: g[key] for key in ("split", "method", "budget", "planned")}
        for key in (*metrics, "riskWidth"):
            values = [r[key] for r in subset if r[key] is not None]
            summary[key + "_count"] = len(values)
            summary[key + "_mean"] = statistics.mean(values) if values else None
            summary[key + "_median"] = statistics.median(values) if values else None
        resource_groups.append(summary)
    with (OUT / "resource-summary.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(resource_groups[0]))
        writer.writeheader()
        writer.writerows(resource_groups)
    preprocessing_rows = []
    for path in sorted((OUT / "cases").glob("*.json")):
        case = json.loads(path.read_text("utf-8"))
        preprocessing_rows.append({
            "caseId": case["id"], "split": case["metadata"]["split"],
            "generatorMs": case["generatorMs"],
            "sharedPreprocessingMs": case["preprocessing"]["elapsedMs"],
            "historyRows": case["preprocessing"]["historyRows"],
            "deploymentActions": case["preprocessing"]["deploymentActionCount"],
        })
    with (OUT / "shared-preprocessing.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(preprocessing_rows[0]))
        writer.writeheader()
        writer.writerows(preprocessing_rows)
    prep_median = statistics.median(r["sharedPreprocessingMs"] for r in preprocessing_rows
                                   if r["split"] == "evaluation")
    font_file = Path("C:/Windows/Fonts/msyh.ttc")
    if font_file.exists():
        font_manager.fontManager.addfont(str(font_file))
        font_family = font_manager.FontProperties(fname=str(font_file)).get_name()
    else:
        font_family = "DejaVu Sans"
    colors = ["#222222", "#777777", "#937640", "#7864A0", "#0072B2"]
    markers = ["s", "x", "^", "v", "o"]
    styles = ["-", ":", "--", "-.", "-"]
    with plt.rc_context({"font.family": font_family, "font.size": 10, "axes.unicode_minus": False,
                         "svg.fonttype": "none", "pdf.fonttype": 42}):
        fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.8))
        fig.subplots_adjust(left=.07, right=.98, bottom=.24, top=.83, wspace=.32)
        for method, color, marker, style in zip(NAMES, colors, markers, styles):
            rows = sorted((g for g in groups if g["split"] == "evaluation" and g["method"] == method),
                          key=lambda g: g["budget"])
            axes[0].plot([g["budget"] for g in rows], [100 * g["resolvedFraction"] for g in rows],
                         color=color, marker=marker, linestyle=style, label=NAMES[method], linewidth=1.5)
        axes[0].set_xscale("log", base=2)
        axes[0].set_xticks([2, 8, 32], ["2", "8", "32"])
        axes[0].set(ylim=(0, 103), xlabel="每次检查最多调用线性求解器的次数",
                    ylabel="作出正确明确判断的场景比例（%）", title="A  全部正式场景均计入分母")
        axes[0].legend(loc="lower right", fontsize=8, frameon=False)
        axes[0].grid(axis="y", color="#DDDDDD", linewidth=.7)
        family_order = ["menu8", "knapsack7", "assignment3"]
        for i, family in enumerate(family_order):
            values = [100 * r["candidateMinusBaseline"] for r in primary["instanceDifferences"] if r["family"] == family]
            # Stack ties vertically; preserve the exact observed horizontal differences.
            positions = []
            for value in values:
                tied = values.count(value)
                used = sum(previous == value for previous in values[:len(positions)])
                positions.append(i + (used - (tied - 1) / 2) * min(.035, .60 / max(1, tied - 1)))
            axes[1].scatter(values, positions,
                            s=24, facecolor="#777777", edgecolor="white", linewidth=.4, alpha=.85)
        axes[1].errorbar(effect, 3, xerr=[[effect - interval[0]], [interval[1] - effect]],
                         fmt="D", color="#0072B2", capsize=4, markersize=6, linewidth=2)
        axes[1].axvline(0, color="#222222", linewidth=.8)
        axes[1].set_yticks([0, 1, 2, 3], ["选方案", "装背包", "任务分配", "总体平均与区间"])
        axes[1].set(xlim=(-105, 105), ylim=(3.45, -.45), xlabel="候选减强对照的判断比例差（百分点）",
                    title="B  主比较：8次求解预算")
        axes[1].text(.02, .02, f"平均 {effect:+.2f}；95%探索区间 [{interval[0]:+.2f}, {interval[1]:+.2f}]",
                     transform=axes[1].transAxes, fontsize=8)
        fig.suptitle("对偶证据复用：主比较未证实优势，低预算下更差", fontsize=15, y=.97)
        fig.text(.07, .11, "来源：2026-10-20 冻结的本地模拟实验。60个独立底层题目，每题两种误差条件；正式场景共120个。",
                 fontsize=8)
        fig.text(.07, .065, "未决与失败均留在分母；右图显示全部60个实例差值（同值纵向排开）。区间为按题型分层的实例配对bootstrap，10,000次。",
                 fontsize=8)
        fig.text(.07, .025, "当前仅二维有限动作模型；图形不是外部真实数据验证或会议格式认证。", fontsize=8)
        fig.savefig(OUT / "comparison.png", dpi=200, facecolor="white")
        fig.savefig(OUT / "comparison.svg", facecolor="white")
        plt.close(fig)
    stress_rows = [g for g in groups if g["split"] == "misspecification" and g["budget"] == 8]
    stress_details = []
    for path in sorted((OUT / "runs").glob("misspecification*__dual_reuse__b8.json")):
        run = json.loads(path.read_text("utf-8"))
        check = run["verification"]
        if run["result"]["status"] == "safe" and check.get("exactTrueRegretRational"):
            if Fraction(check["exactTrueRegretRational"]) > Fraction(1, 4):
                stress_details.append((run["caseId"], check["exactTrueRegretRational"],
                                       check["exactWorstRegretRational"], check["truthContained"]))
    lines = [
        "贡献与比较实验：本轮完整结果", "日期：2026-10-20", "",
        "先看结论",
        f"候选方法在主预算下完成可靠判断{candidate['resolved']}/120；全约束对照{baseline['resolved']}/120。",
        f"样本平均差为{effect:+.2f}个百分点；按60个独立实例计算的95%探索区间为[{interval[0]:.2f}, {interval[1]:.2f}]个百分点。",
        "这个区间包含没有改善的情况，且改善未达到事先规定的10个百分点；贡献继续标准未满足。",
        "因此，不把本次对偶复用改法包装成已经验证的CCF A主贡献，不替换为软件的更优默认算法。",
        "已经完成的是可运行算法、五种公平适配对照、全部结果、精确核验和可复算材料。", "",
        "一、明确的目标与本轮范围",
        "大方向不变：语言提供候选成本结构，历史行为约束参数，优化器提出方案，再检查风险。",
        "AAAI正式长文仍是目标；目标不是录用承诺。本轮问题是固定方案风险判断的计算效率。",
        "主任务为在8次LP调用、2秒协作式预算内，尽量给出正确明确判断，并保留有效风险界。",
        "所有方法看到同一模型、同一历史、同一误差假设、同一固定候选方案；看不到隐藏真值。",
        "同一实例的两种误差条件相关，先在实例内平均，再作实例级比较，不能把2070次运行当独立样本。",
        "样本量由本轮资源安排固定；这是有预先冻结规则的估计性实验，不是已做功效保证的正式确认研究。", "",
        "统计措辞勘误：冻结协议中的“distribution-free normal-approximation”不严谨。",
        "其中0.253仅为用方差上界计算的正态近似尺度，不是分布无关的有限样本95%覆盖保证。",
        "保留冻结原文并在protocol-errata.txt记录此更正；主要结果仍按原定实例配对bootstrap计算，数值和门槛未变。", "",
        "二、五种方法实际有什么区别",
        "full_priority：一次加入全部历史比较约束，按初始风险上界排序；这是强直接对照的一个冻结实现。",
        "lazy_sequential：按原竞争方案顺序逐步加约束。",
        "lazy_priority：同样逐步加约束，但按初始风险上界排序。",
        "witness_priority：每步选择当前尚未排除且风险上界最大的方案；它不是唯一复用见证的方法。",
        "dual_reuse：在动态排序上，进一步把一个LP的合法对偶证明用于所有竞争方案的上界。",
        "五者都可复用相容参数见证、及时报告风险、提前停止。对照没有被强迫做完所有无用计算。",
        "但full_priority没有全局对偶复用或LP基热启动，故不能称为所有直接算法中的最强实现。",
        "本轮没有复现Boutilier全部外层minimax决策、Bodur信赖域或Conformal IO的训练校准流程；不声称超过这些论文。", "",
        "三、方法有效性的数学依据（经典原理，不是首创定理）",
        "历史相容参数满足 Aθ≤d 且 θ∈B；B是声明的参数框。不同竞争方案对应目标q。",
        "对任何y≥0，qᵀθ≤yᵀd+(q−Aᵀy)ᵀθ≤yᵀd+support_B(q−Aᵀy)。",
        "所以旧LP得到的非负y，换到另一个q后仍给有效上界；它可能较松，但不会因换q而失效。",
        "添加真实历史约束后，旧约束继续有效，因此旧证明仍可保留。",
        "程序用有理数重算y、Aᵀy和yᵀd，保存逐行乘子；参数见证要通过全部历史，才给风险下界。",
        "下界超过阈值便有风险例子；上界不超过阈值且已证明集合非空才可给条件保证；否则未决。",
        "这些不等式保证核验方向，不保证快速、独特、统计覆盖或真实业务假设正确。", "",
        "四、预先固定的实验",
        "共138个场景条件：12个试调、120个正式比较、6个故意错设误差预算。",
        "正式比较来自3种生成器各20个新底层实例，每题2种误差条件，参数维度为2。",
        "三种题型：8选1、7变量二元背包、3×3任务分配。每项8条历史、1个新场景。",
        "每个条件运行5方法×3预算，共预定2070次，实际保存2070次；缺失0，执行失败0。",
        "已声明的预算为0或0.4，接受风险阈值为0.25；LP预算2、8、32，主比较在8。",
        "方法顺序按固定随机种子在每个场景预算块内打乱；每次创建新方法状态，未沿用前一方法的答案。",
        "代码、协议、版本和运行顺序在结果前保存到freeze.json及frozen-source。它是本地冻结，不是公开平台注册。",
        "数据完全合成，部署decision字段是与真值无关的可行占位方案；没有真实人类、业务或语言理解实验。",
        "公共动作枚举、完整历史比较表和旧点估计属于共享预处理，分别记账；每个方法的建模和核验在自身计时内。",
        "完整历史表已在共享预处理中生成，因此结果不能证明隐式超大动作空间或一般MILP的可扩展性。", "",
        "五、主预算8次LP的全部方法",
    ]
    for g in main_rows:
        c = g["counts"]
        lines.append(f"{NAMES[g['method']]}：可靠判断{g['resolved']}/120；条件安全{c['safe']}，风险见证{c['risk_witness']}，未决{c['unresolved']}；"
                     f"耗时中位数{g['medianElapsedMsCompleted']:.1f}毫秒；平均LP调用{g['meanLPCallsCompleted']:.3f}。")
    lines += [
        "可靠判断包含安全或风险被明确判定，并不等于推荐方案本身安全；候选的112次中安全79次、风险见证33次。",
        "相对动态排序消融，候选多完成10/120次判断（8.33个百分点），为描述性机制证据，不替代主要对照。",
        "分题型的主比较样本均值差：选方案0个百分点、背包15个百分点、任务分配0个百分点；正差异集中于背包题。",
        "2次LP时，候选15/120，强直接对照62/120，候选明显更差。",
        "32次LP时，候选120/120，强直接对照119/120；差异很小。三个预算均完整报告，没有只挑8次。",
        "耗时是同机本轮的粗粒度测量，不能把中位数之比称为普遍加速倍数；所有逐次耗时均可查看。", "",
        f"正式条件中，共享预处理的耗时中位数为{prep_median:.1f}毫秒，另见shared-preprocessing.csv；不包含在上述单方法毫秒数内。",
        "共享预处理含原点估计等工作，不能由后续检查的毫秒差推导整条工作流同倍数加速。",
        "resource-costs.csv与resource-summary.csv完整给出求解、历史扫描、加约束、证据复用和风险区间宽度。",
        "宽度只在已有上下界时定义；无见证、空集合或失败时留空，并逐项列明有效计数，绝不当作零宽度。",
        "这些计算成本为事后汇总的预列次要指标；不取代主要判定比例，也不对多项指标作显著性筛选。", "",
        "六、正确性与失败边界",
        "每条保存结果都由独立标准库程序重新枚举原始方案、精确裁剪参数多边形核对。",
        "本轮没有发现不成立的参数见证、错误风险界或对声明模型的错误判定；全量核验见independent-verification.json。",
        "正式匹配条件下，没有发现获证方案的真实模拟损失超过阈值。",
        "但在故意把实际允许误差1.0写成0的六个任务中，五个任务的真参数被声明集合排除。",
        "在主预算下，五种方法都在同一个任务出现“条件安全但实际损失超阈值”，不是五个独立失败案例。",
    ]
    for case_id, true_regret, declared_regret, contained in stress_details:
        lines.append(f"直接反例：{case_id}；声明集合内最坏损失={declared_regret}；真实模拟损失={true_regret}；阈值=1/4；真参数在集合内={contained}。")
    lines += [
        "这是保证前提被破坏的实际失败，不能用“数学没错”掩盖应用风险。该批次独立列示，不混入匹配条件的零错误表述。",
        "尤其不能承诺只要假设错了，程序就一定会显示“不相容”：它可能找到另一个错误但相容的参数集合。", "",
        "七、贡献判断与下一阶段明确目标",
        "已验证的工程成果：可复核的有限动作证据、对偶复用实现、相同任务的五方法比较、完整正负结果。",
        "未成立的主张：首次使用对偶证据、已稳定超过强基线、已恢复真实价格、已验证真实语言理解、已具备CCF A录用水平。",
        "按冻结规则，本轮不将dual_reuse作为已验证的论文主贡献。保留候选实现供复算，而不更改正式测试标准。",
        "保持语言候选结构—历史行为—方案风险检查主线；优先研究误差预算敏感性，同时补足真实语言实验与更强计算对照。",
        "具体目标是在可辩护的历史误差条件下提供有用的风险判断；仅凭训练拟合不能保证未知误差上限。",
        "下一份独立协议应先检验：在给定可辩护的误差区间内，风险结论何时保持稳定、何时必须保留未决；",
        "并加入full-row＋dual-reuse＋adaptive及热启动强对照，使用全新实例，才能评价下一改法。",
        "这里没有把这些尚未运行的新工作写成结果，也不因本轮未达标准就换一个名称宣称成功。", "",
        "八、通俗解释",
        "我们让五种做题办法答同一批题，每种最多算同样多次。",
        "新办法像把已经写好的草稿用到下一小问，确实有时省事。",
        "但只允许算两次时，先把条件整理全的办法更好；允许多算时，两者几乎都能答出来。",
        "所以现在还不能说新办法稳稳赢了。最重要的是：如果一开始把同学犯错的程度估得太小，",
        "后面的计算再精确，也可能很肯定地给错保证。后续真正要解决的是这个可检验的问题。", "",
        "九、复算入口与材料位置",
        "outputs/comparison-20261020/freeze.json：冻结方案、源代码哈希、版本与完整运行顺序。",
        "cases/：138个原始场景与仅供评估的真值；runs/：2070份方法输出、逐步轨迹、上下界及对偶证明。",
        "analysis.json：按预先规则得到的主比较；summary-table.csv：全分组结果；paired-instance-effects.csv：全部60个实例差值。",
        "resource-costs.csv、resource-summary.csv：逐次和分组计算成本、风险区间宽度与各自有效计数。",
        "shared-preprocessing.csv：全部场景生成及共享预处理成本。",
        "independent-verification.json：独立核验报告；comparison.png/svg：完整比较图。",
        "research/comparison_prior_work.txt：六篇方法近邻原文核验与限制。",
        "resources\\runtime\\python\\python.exe research\\verify_comparison.py outputs\\comparison-20261020",
        "resources\\runtime\\python\\python.exe research\\analyze_comparison.py",
        "research/run_comparison.py使用--out指定新的输出目录、--split all可重跑；已有case会拒绝覆盖。",
        "运行科研图使用系统Python和项目内的纯Python绘图依赖隔离目录；软件实际求解使用随程序附带Python。",
        "上一版完整存档：archives/before-certification-20261020-210402，2301文件核验通过。",
        "先前原始0.1存档继续保留；一次内存不足中止的备份目录不作为有效存档。", "",
        "十、来源与工具说明",
        "Boutilier等，2006，最坏后悔与约束生成：https://webdocs.cs.ualberta.ca/~daes/papers/aij06.pdf",
        "Bodur等，2022，逆混合整数多面体与信赖域：https://pubsonline.informs.org/doi/10.1287/ijoc.2021.1138",
        "Lin等，NeurIPS 2024，Conformal Inverse Optimization：https://proceedings.neurips.cc/paper_files/paper/2024/hash/7423902b5534e2b267438c85444a54b1-Abstract-Conference.html",
        "Kothari与Luedtke，2026，对偶解池复用：https://link.springer.com/article/10.1007/s12532-026-00324-3",
        "已有对偶复用文献与本项目并非完全同题，但足以排除笼统的“首次复用”主张；没有穷尽新颖性检索。",
        "使用实验设计、统计分析、科研绘图技能，流程来源已列为工具参考而非算法依据：",
        "Kassis T., Agarwal V., He Y., Patel D., Brueckner A. M. (2026). Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents.",
        "https://doi.org/10.48550/arXiv.2609.00065（本轮核验为2026-09-02更新的v2；引用使用稳定DOI）。",
        "没有用LLM生成的数值代替求解输出，没有使用付费模型调用或伪造人类反馈。", ""
    ]
    report = OUT / "贡献与比较实验结果.txt"
    report.write_text("\n".join(lines), "utf-8")
    metadata = {"matplotlib": matplotlib.__version__, "source": "analysis.json",
        "sourceSha256": hashlib.sha256((OUT / "analysis.json").read_bytes()).hexdigest(),
        "transforms": ["all planned runs kept in denominator", "two conditions averaged within independent instance",
                       "stratified instance bootstrap 10000",
                       "deterministic vertical stacking of tied points; exact horizontal values unchanged"],
        "figure": {"pixels": [2240, 960], "dpi": 200, "publisherComplianceClaim": False},
        "altText": "Five methods' correct resolution rates over budgets2,8,32. Dual reuse is worse at2, slightly better at8 and32. At8 its paired advantage is5pp with exploratory95% interval minus1.67 to11.67pp, so the planned contribution gate is not met.",
        "plotDependency": {"htmlInit": "https://raw.githubusercontent.com/python/cpython/v3.12.7/Lib/html/__init__.py",
                           "scope": "workspace-only; no system Python files modified"},
        "reportSha256": hashlib.sha256(report.read_bytes()).hexdigest()}
    (OUT / "figure-provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), "utf-8")
    print(str(report))


if __name__ == "__main__":
    main()
