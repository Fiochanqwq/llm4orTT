"""Render Chinese deliverables from audited evidence; never rerun a solver."""
import argparse
import csv
import hashlib
import html
import json
import statistics
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "full_priority": "完整约束",
    "dual_reuse": "逐步约束＋复用",
    "full_adaptive_dual": "完整约束＋动态复用",
    "full_warm_adaptive_dual": "动态复用＋热启动",
}
FAMILIES = {"menu8": "菜单选择", "knapsack7": "二元背包", "assignment3": "人员指派"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnostics(out, analysis, frozen):
    p = frozen["protocol"]
    runs = [read(path) for path in (out / "comparison/runs").glob("*.json")]
    index = {(r["caseId"], r["method"], r["budget"]): r for r in runs}
    discordances = []
    for identifier in dict.fromkeys(r["caseId"] for r in frozen["comparisonSchedule"]):
        a = index[(identifier, p["primary_candidate"], p["primary_lp_budget"])]
        b = index[(identifier, p["primary_comparator"], p["primary_lp_budget"])]
        resolved = lambda r: r["executionStatus"] == "complete" and r["result"]["status"] in (
            "safe", "risk_witness", "incompatible")
        if resolved(a) != resolved(b):
            case = read(out / "comparison/cases" / (identifier + ".json"))
            discordances.append({
                "caseId": identifier, "family": case["metadata"]["family"],
                "candidateStatus": a["result"]["status"], "baselineStatus": b["result"]["status"],
                "candidateStop": a["result"].get("stopReason"),
                "baselineStop": b["result"].get("stopReason"),
                "candidateLpCalls": a["result"]["resources"]["lpCalls"],
                "baselineLpCalls": b["result"]["resources"]["lpCalls"],
                "historyRows": case["preprocessing"]["historyRows"],
                "deploymentActions": case["preprocessing"]["deploymentActionCount"],
            })
    stops = Counter((r["method"], r["budget"], r["result"].get("stopReason", "unknown"))
                    for r in runs if r["executionStatus"] == "complete" and r["result"]["status"] == "unresolved")
    examples, transitions = [], Counter()
    for path in (out / "sensitivity/profiles").glob("*.json"):
        row = read(path)
        if row["executionStatus"] != "complete" or row["cap"] != p["primary_sensitivity_cap"]:
            continue
        checks = row["verification"]
        nominal = checks["nominal"]
        upper = checks["upper"]
        transitions[(nominal["status"], upper["status"])] += 1
        actual = Fraction(nominal["exactTrueRegretRational"])
        threshold = Fraction(nominal["thresholdRational"])
        if nominal["status"] == "safe" and actual > threshold:
            examples.append({
                "caseId": row["caseId"], "trueRegret": float(actual),
                "trueRegretExact": str(actual), "threshold": float(threshold),
                "nominalStatus": nominal["status"], "upperStatus": upper["status"],
                "nominalTruthContained": nominal["truthContained"],
                "upperTruthContained": upper["truthContained"],
                "evidence": path.relative_to(out).as_posix(),
            })
    family_effects = []
    for family in p["families"]:
        values = [r["difference"] for r in analysis["primary"]["instanceDifferences"] if r["family"] == family]
        family_effects.append({"family": family, "n": len(values), "meanDifference": statistics.mean(values),
                               "sdDifference": statistics.stdev(values),
                               "negative": sum(v < 0 for v in values), "zero": sum(v == 0 for v in values),
                               "positive": sum(v > 0 for v in values)})
    result = {
        "schema": "publication-diagnostics.v1", "scope": "Descriptive post-result mechanism diagnosis; no new confirmatory tests.",
        "discordances": discordances, "falseSafeExamples": sorted(examples, key=lambda r: r["caseId"]),
        "familyEffects": family_effects,
        "unresolvedReasons": [{"method": k[0], "budget": k[1], "reason": k[2], "count": v}
                              for k, v in sorted(stops.items())],
        "primaryTransitions": [{"from": k[0], "to": k[1], "count": v} for k, v in sorted(transitions.items())],
    }
    save(out / "diagnostics.json", result)
    for name, rows in (("discordant-cases", discordances), ("false-safe-cases", examples),
                       ("family-effects", family_effects)):
        if rows:
            with (out / (name + ".csv")).open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    return result


def figures(out, a, d, font):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont(str(font))
    family = font_manager.FontProperties(fname=str(font)).get_name()
    folder = out / "figures"
    folder.mkdir(exist_ok=True)
    colors = ["#677586", "#A14F28", "#297E83", "#233C63"]
    with plt.rc_context({"font.family": family, "font.size": 10, "axes.unicode_minus": False,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "path", "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(9.6, 4.5), layout="constrained")
        methods = list(LABELS)
        budgets = sorted({g["budget"] for g in a["comparisonGroups"]})
        for j, method in enumerate(methods):
            groups = [next(g for g in a["comparisonGroups"] if g["budget"] == b and g["method"] == method) for b in budgets]
            xpos = [i + (j - 1.5) * .19 for i in range(len(budgets))]
            bars = ax.bar(xpos, [100 * g["resolvedFraction"] for g in groups], width=.18,
                          color=colors[j], label=LABELS[method], hatch=["", "//", "..", "xx"][j])
            for bar, g in zip(bars, groups):
                ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1.3,
                        str(g["resolved"]), ha="center", fontsize=8)
        ax.set(xticks=range(len(budgets)), xticklabels=budgets, ylim=(0, 113),
               xlabel="每次方法运行允许的 LP 调用次数", ylabel="得到经核验明确结论的比例（%）",
               title="图 1｜同一方案、同一预算下的四种证书计算方法")
        ax.legend(ncols=2, fontsize=9, loc="upper center", bbox_to_anchor=(.5, -.19))
        ax.grid(axis="y", alpha=.15)
        fig.savefig(folder / "resolution.png", dpi=300, facecolor="white")
        fig.savefig(folder / "resolution.svg", facecolor="white")
        plt.close(fig)

        fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0), layout="constrained")
        groups = a["sensitivityGroups"]
        names = [str(g["cap"]) for g in groups]
        for ax, key, title, ylabel, color in (
            (axes[0], "upperActualFalseSafe", "图 2a｜真实损失超阈值却被放行", "错误放行数（个 / 120）", "#A14F28"),
            (axes[1], "rangeSafe", "图 2b｜较宽预算下仍可安全放行", "条件安全数（个 / 120）", "#233C63"),
        ):
            bars = ax.bar(names, [g[key] for g in groups], color=color, width=.55)
            ax.set(title=title, xlabel="明确声明的历史误差上限", ylabel=ylabel, ylim=(0, 120))
            ax.grid(axis="y", alpha=.15)
            for bar, g in zip(bars, groups):
                ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+2, str(g[key]), ha="center")
        fig.savefig(folder / "sensitivity.png", dpi=300, facecolor="white")
        fig.savefig(folder / "sensitivity.svg", facecolor="white")
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(9.6, 3.8), layout="constrained")
        offsets = {"menu8": 0, "knapsack7": 1, "assignment3": 2}
        for row in d["familyEffects"]:
            counts = [row["negative"], row["zero"], row["positive"]]
            left = 0
            for count, color, label in zip(counts, ["#A14F28", "#CBD1D6", "#297E83"],
                                           ["候选较差", "相同", "候选较好"]):
                ax.barh(offsets[row["family"]], count, left=left, color=color,
                        label=label if row["family"] == "menu8" else None)
                if count:
                    ax.text(left+count/2, offsets[row["family"]], str(count), ha="center", va="center")
                left += count
        ax.set(yticks=[0, 1, 2], yticklabels=[FAMILIES[f] for f in offsets],
               xlim=(0, 40), xlabel="独立实例数（每类 40 个；两种噪声先在实例内平均）",
               ylabel="固定生成器类别", title="图 3｜主比较逐实例差值的方向")
        ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(.5, -.20))
        fig.savefig(folder / "paired-instances.png", dpi=300, facecolor="white")
        fig.savefig(folder / "paired-instances.svg", facecolor="white")
        plt.close(fig)
    save(folder / "provenance.json", {
        "source": "../analysis.json; ../diagnostics.json", "date": "2026-10-21",
        "matplotlib": matplotlib.__version__, "dpi": 300, "formats": ["PNG", "SVG"],
        "transformations": ["resolution/planned*100", "counts at each frozen cap",
                            "sign of paired within-instance mean difference"],
        "replicateUnit": "family-seed; 120 per cohort", "missingPolicy": "planned denominators retained",
        "uncertainty": "Figure 3 shows observed signs, not confidence intervals; primary bootstrap interval is in text.",
        "publisherCompliance": "General research-report figures; AAAI submission formatting not asserted.",
    })


def content(a, audit, d, frozen, engineering, amendment=None):
    p = a["primary"]
    main = {g["method"]: g for g in a["comparisonGroups"] if g["budget"] == p["budget"]}
    sg = next(g for g in a["sensitivityGroups"] if g["cap"] == frozen["protocol"]["primary_sensitivity_cap"])
    low_cap = min(a["sensitivityGroups"], key=lambda g: g["cap"])
    delta = 100*p["pairedDifference"]
    ci = [100*v for v in p["exploratory95Interval"]]
    gate = "达到" if p["candidatePromotionGateMet"] else "未达到"
    verdict = (f"候选方法相对强对照的明确判断率差值为 {delta:+.2f} 个百分点，"
               f"95% 探索性区间为 [{ci[0]:.2f}, {ci[1]:.2f}]。{gate}预先规定的继续投入门槛。")
    sections = [
        ("01", "结论先行", [
            "本轮完成了实验基础设施整合、一次全新的冻结合成研究，以及逐项独立精确核验。"
            "研究目标仍为 AAAI 正式长文；目前没有足够证据宣布投稿已就绪。",
            verdict,
            f"2,880 次方法运行、360 个双端点档案（720 次端点检查）均进入完整排程。"
            f"主比较中，候选方法明确判断 {main[p['candidate']]['resolved']}/240，"
            f"强对照为 {main[p['comparator']]['resolved']}/240。",
            f"已知合成误差上限为 1 时，按较小预算 0 检查出现 {sg['nominalActualFalseSafe']} 个真实错误放行；"
            f"将声明上限设为 1 后为 {sg['upperActualFalseSafe']} 个，仍有 {sg['rangeSafe']}/120 个条件安全方案。"
            "这是正确假设下的合成机制证据，不是现实世界零风险保证。",
            "用大白话说：先拿同一张购物清单让四位检查员查账，再看谁能在相同计算额度内查清。"
            "如果我们一开始把“同学可能多花多少钱”估得太低，账本算对了也可能放过危险买法。"
            "把误差假设写清楚，与证明算法算得对，是两件需要分别完成的事。",
        ]),
        ("02", "结构整合与工程验收", [
            "维护源固定为 solver/、server/、src/；research/ 保存实验协议、生成器、方法与独立复核器。"
            "resources/ 仍是程序发布副本。本轮修改集中在研究适配器、调度入口和 CI，未修改生产求解器或界面源码。",
            "新增 experiment_runtime.py，统一原子 JSON 写入、文件摘要、不可覆盖的结果记录及系统级写入锁。"
            "run_comparison.py 和 run_followup.py 共用这些存储原语；既有命令入口保留。",
            "修复研究适配器把风险阈值固定为 1/4、把参数框固定为 [0,2] 的问题；现在从声明输入读取。"
            "恢复运行直接重建已保存方案的输入，不重新拟合，从而避免重启后悄悄换一个方案。",
            "新的单入口依次执行测试、前端构建、真实 HTTP 验收、冻结排程、算法计算、独立核验与统计。"
            f"{engineering['pythonTests']} 项 Python 研究与完整性测试、{engineering['nodeTests']} 项 Node 应用测试通过，证书测试已加入 CI。"
            "TypeScript 检查及前端构建通过；构建仍提示主 JavaScript 包较大。",
            "HTTP 验收使用隔离工作目录：未认证请求被拒绝；真实 Python 拟合与双端点检查完成；"
            "结果可以保存、列出及原样读回。新增模型调用为 0。"
            + ("五个生产求解器文件与 resources/solver 中的发布副本逐字节一致。"
               if engineering["productionSolverCopiesMatch"] else "生产源码与发布副本存在差异，详见 engineering-verification.json。"),
            "最初沙箱阻止本机 HTTP 连接；该失败日志保留。允许本机连接后验收通过，科学冻结在此之后。"
            "这是运行环境修复，不是删掉不利的科学结果。",
        ]),
        ("03", "冻结设计与数学边界", [
            "比较队列：三类固定生成器，每类 40 个新种子（51001 至 51040），每个实例使用误差 0 与 0.4；"
            "四方法、三档 LP 调用上限（2、8、32），共 2,880 次运行。"
            "敏感性队列使用不重叠的新种子（61001 至 61040），每类 40 个实例，真实合成误差上限为 1；"
            "名义声明为 0，较宽声明分别为 0.4、1、2。",
            "每个输入含 8 条历史、1 个新部署情境和 2 个未知参数。旧点估计只拟合一次，部署方案固定。"
            "方法接收不含真值的成本、约束与预算；隐藏真值仅由外部评估器用来查账。",
            "单次比较最多 2 秒；敏感性两个端点分别最多 2 秒与 256 次历史检查。"
            "时间限制是协作式限制，精确算术可能略微超时。敏感性研究不被包装成等 LP 预算的速度比较。",
            "相容集合 U 保留所有同时符合参数框与历史次优预算的参数。对固定方案 x，核验"
            " R(x;U)=max[成本(x,θ)−成本(y,θ)]，其中 θ 属于 U，y 遍历可行方案。"
            "safe 必须同时有非空相容集合证据和不超过阈值的上界；空集不会被当作安全。",
            "独立核验器使用有理数裁剪二维多边形，重新枚举原始方案并计算精确风险，"
            "不依赖被测方法保存的“验证通过”标记。验证对象是输入的数值模型，"
            "不自动证明自然语言理解、遗漏特征、参数框或现实误差上限正确。",
            "主估计先在同一实例内平均两种噪声差值，再对三类等权平均；"
            "每类内以实例为单位做 10,000 次配对自助重抽样。区间为探索性精度描述，"
            "没有正态性断言、事后换检验或多重显著性筛选。每队列只有 120 个独立实例。",
        ]),
        ("04", "算法比较：保留全部预算与对照", [
            verdict,
            f"同一主预算下，候选相对原完整约束对照的判断率差值为 "
            f"{100*(main[p['candidate']]['resolvedFraction']-main['full_priority']['resolvedFraction']):+.2f} 个百分点。"
            "这项描述性对照说明：是否加入更强的动态调度与复用基线，会直接影响我们对候选价值的判断。"
            "它不替代事先指定的主比较。",
            "继续投入门槛在新结果出现前固定：主差值至少 +10 个百分点、探索性区间下端大于 0、"
            "全排程完成且无无效证书。门槛通过也只意味着值得继续研究，不能单独证明新颖性。",
            "完整约束：一次性装入全部历史约束；逐步约束＋复用：逐步加入约束并复用证据；"
            "完整约束＋动态复用：动态选择竞争方案、共享证据；动态复用＋热启动："
            "在前者基础上，记录 HiGHS 实际接受的单纯形基。四者认证同一个方案。",
            f"主比较有 {len(d['discordances'])} 个噪声条件在候选与强对照之间出现“是否明确判断”的差异。"
            "逐项记录在 discordant-cases.csv；它们属于事后机制诊断，不是新增独立试验。",
            "时间中位数、LP 调用数、累计约束行和实际热启动次数均保留。"
            "本机还承担文档准备任务，因此时间仅作描述，不宣称专用硬件上的速度优势。",
        ]),
        ("05", "误差错设：安全与可用性一起看", [
            f"主敏感性条件（较宽预算 1）下，名义预算错误放行 {sg['nominalActualFalseSafe']} 个，"
            f"较宽预算错误放行 {sg['upperActualFalseSafe']} 个。"
            f"{sg['nominalFalseSafeNotReleasedAtUpper']} 个名义错误放行未再获得较宽范围安全标签。",
            f"较宽预算仍允许 {sg['rangeSafe']}/120 个方案获得条件安全结论。"
            "同时报告能放行多少，避免靠“永远拒绝”制造安全表象。",
            "真实参数不在声明相容集合内时，安全证书可能在数学上完全成立，但不能保护这组真实参数。"
            "报告把“算式错了”和“前提不对”分开：前者阻断正确性结论，后者保留为有价值的反例。",
            "0.4 是低估预算，1 与生成器已知上限一致，2 是更保守的预算。"
            "较宽集合通常保留更多可能价格，安全放行因此可能减少。"
            "这些上限提前固定，没有看完结果再挑最好的一档。",
            f"低估预算 {low_cap['cap']} 本轮也只观察到 {low_cap['upperActualFalseSafe']} 个错误放行，"
            f"但仍把 {low_cap['upperTruthExcluded']}/120 个真实参数排除在声明集合外。"
            "这说明不能凭“这一次没出事”倒推误差假设已经可靠。"
            "不同上限下的安全数也受不相容集合变为非空影响，不能只看安全数的单调性。",
            "旧 assignment3-s20011 反例另做回归核验，不计入新队列。"
            "两个端点不能估计临界预算，也不能从合成结果推出真实业务应当使用上限 1。",
        ]),
        ("06", "负结果如何变成下一轮可检验问题", [
            "已完成的建设：把分散脚本接成冻结、执行、审计、统计的单入口；"
            "修正输入契约中的硬编码；对失败、中断和源代码漂移设立明确处理规则；"
            "使用强对照和新种子复核旧候选，而不是只重复开发阶段容易获胜的例子。",
            "计算路线：逐项对照 discordant-cases.csv 中的停止原因、历史行数、竞争方案数和 LP 次数，"
            "判断瓶颈来自约束发现还是数值提案。新的调度策略必须使用开发队列选择，"
            "随后用另一个从未查看的种子队列验证，不能在本轮测试集上调参后重报主结果。",
            "安全路线：下一项独立语言任务研究应将“真实坏方案被放行的比例”与“仍可用的方案比例”"
            "同时作为结果，并冻结每种方法相同的模型、提示、信息与预算。"
            "误差上限的现实依据必须单独提供，不能用训练拟合误差冒充保证。",
            "结构路线：另列参数框错设、遗漏成本特征、遗漏硬约束和部署成本变化的干预；"
            "完整保留未决、无解、解析错误与修补失败。每种干预应先验证生成器确实产生该错设，"
            "再判断风险审计是否有用。",
            "文献边界：TACIT 已将语言模型结构修补与行为校准相结合，并使用历史方案与用户改正。"
            "本轮没有复现 TACIT，也没有匹配其监督条件。弱对偶、集合包含、约束生成和热启动"
            "均不作为首次发明。本报告提供可靠性与反例证据，尚未建立足够的论文新颖性。",
        ]),
        ("07", "证据账本、复算与未完成事项", [
            "新证据：这是结果产生前的本地冻结，不是公开预注册。freeze.json 保存协议、随机排程、运行环境及源码摘要；frozen-source/ 保存源码副本；"
            "comparison/ 保存所有输入和比较结果；sensitivity/ 保存双端点档案；"
            "independent-followup-audit.json 保存独立复核；analysis.json 保存预定统计；"
            "diagnostics.json 是明确标注的事后诊断。",
            "旧语言证据单独审计：1,355 个文件哈希及 141,969 项证据/算术检查通过，"
            "涵盖历史 2,912 行结果与 397 条模型调用记录。旧数据包含失败与来源阻断，"
            "不被计作本轮新实验，不代表每个求解器最优值或文本语义都被独立证明。",
            "操作日志与代码使用英文，交付说明使用中文。可用 npm run experiment:publication 执行新批次；"
            "已有批次使用 --resume，并验证环境与源码没有变化；npm run audit:publication 重新审计。"
            "修改已冻结的源码后必须另建批次或使用冻结源码复算，不能沿用旧成绩。",
            "仍未完成：新的独立语言风险任务、监督匹配的文献强基线、真实人类决策验证、"
            "一般连续/大规模 MILP 证书扩展、现实噪声上限校准及论文新颖性证明。"
            "这些指标保持未测，不补写成成功。",
            "工作流参考了 Scientific Agent Skills 的实验设计、统计与科学绘图流程；"
            "论文与工具引用见下方。图表是通用研究报告格式，未声称已经满足当届 AAAI 投稿版式。",
        ]),
    ]
    if amendment:
        sections[1][2].append(
            "第一版独立审计因旧反例复制后文件名与实例 ID 不一致而拒绝放行。"
            "本次交付是明确标记的归档修正版：保留失败审计和原冻结源码，"
            "只纠正该反例的文件关联；3,600 个科学输入与结果文件逐字节不变，未新增或重跑实验。"
            "未来批次的复制逻辑已修复，并补上完整的独立核验回归测试。")
        sections[6][2].insert(2,
            "归档修正记录见 archive-amendment.json，原失败审计见 audit-history/。"
            "frozen-source/ 保留实际运行时的旧源码；delivery-source/ 单列报告与归档修复代码，"
            "不把修复后的代码冒充事前执行版本。实际恢复检查验证 3,600 个原始文件无变化、零新增运行。"
            "当前源码已有归档修复，因此对旧冻结批次执行 --resume 会按设计拒绝源码漂移。"
            "本归档可直接用 verify_followup.py 独立复核；新实验必须指定新的批次目录。")
    return sections


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--plot-deps", type=Path, default=ROOT / "work/research/plot-deps")
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msyh.ttc"))
    args = parser.parse_args()
    sys.path.insert(0, str(args.plot_deps))
    out = args.out.resolve()
    a, audit, frozen = [read(out / n) for n in (
        "analysis.json", "independent-followup-audit.json", "freeze.json")]
    if not audit["allPassed"] or not a["comparisonComplete"] or not a["sensitivityComplete"]:
        raise RuntimeError("A completed report requires complete, independently audited evidence.")
    d = diagnostics(out, a, frozen)
    figures(out, a, d, args.font)
    engineering = read(out / "engineering-verification.json")
    amendment = read(out / "archive-amendment.json") if (out / "archive-amendment.json").exists() else None
    sections = content(a, audit, d, frozen, engineering, amendment)
    refs = [
        ("Bouscary et al. (2026). TACIT: Optimization Models that Learn from Their Mistakes. arXiv:2609.38434.",
         "https://arxiv.org/abs/2609.38434"),
        ("Huangfu & Hall (2018). Parallelizing the dual revised simplex method. Mathematical Programming Computation, 10, 119-142.",
         "https://doi.org/10.1007/s12532-017-0130-5"),
        ("NIST/SEMATECH. e-Handbook of Statistical Methods: Randomized block designs.",
         "https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm"),
        ("Kassis, Agarwal, He, Patel & Brueckner (2026). Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents. arXiv:2609.00065.",
         "https://arxiv.org/abs/2609.00065"),
    ]
    save(out / "references.json", {"verifiedDate": "2026-10-21", "items": [{"title": t, "url": u} for t, u in refs]})
    render_pdf(out, sections, a, d, frozen, refs, args.font)
    render_html(out, sections, a, d, refs)
    (out / "实在结论.txt").write_text("\n\n".join(sections[0][2]) +
        "\n\n完整交付：研究报告.pdf；完整研究报告.html\n复算说明：research/REPRODUCE_PUBLICATION.txt\n", encoding="utf-8")
    save(out / "report-provenance.json", {
        "rendererSha256": digest(Path(__file__)),
        "inputHashes": {n: digest(out / n) for n in ("analysis.json", "independent-followup-audit.json", "freeze.json")},
        "reportLanguage": "zh-CN", "sourceVerified": True, "newModelCalls": 0,
    })
    print(json.dumps({"pdf": str(out / "研究报告.pdf"), "html": str(out / "完整研究报告.html")}, ensure_ascii=False))


def render_pdf(out, sections, a, d, frozen, refs, font):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image
    pdfmetrics.registerFont(TTFont("ReportZH", str(font)))
    pdfmetrics.registerFont(TTFont("ReportBold", "C:/Windows/Fonts/msyhbd.ttc"))
    body = ParagraphStyle("Body", fontName="ReportZH", fontSize=10, leading=16.5,
                          spaceAfter=11, textColor=colors.HexColor("#293749"), wordWrap="CJK")
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=12, spaceAfter=5)
    title = ParagraphStyle("Title", parent=body, fontName="ReportBold", fontSize=23, leading=33, spaceAfter=20)
    subtitle = ParagraphStyle("Subtitle", parent=body, fontSize=10, leading=15, textColor=colors.HexColor("#53657A"))
    section_title = ParagraphStyle("Section", parent=title, fontSize=20, leading=28)
    story = []
    def para(text, style=body):
        return Paragraph(html.escape(text), style)
    def table(headers, rows, widths):
        values = [[para(str(v), small) for v in row] for row in [headers, *rows]]
        tab = Table(values, colWidths=widths, repeatRows=1, hAlign="LEFT")
        tab.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F5")),
            ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor("#9DAFBD")),
            ("LINEBELOW", (0, 1), (-1, -1), .25, colors.HexColor("#DAE1E7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return tab
    for number, heading, paragraphs in sections:
        if number != "01":
            story.append(PageBreak())
        story += [para("LLM4ORTT 0.1.2  /  2026-10-21  /  本地冻结研究", subtitle),
                  para(("可靠性先于漂亮分数" if number == "01" else heading), title if number == "01" else section_title)]
        if number == "01":
            story += [para("结构整合、独立复核与噪声边界实验", subtitle), Spacer(1, 8)]
        for text in paragraphs:
            story.append(para(text))
        if number == "02":
            story.append(table(["原来的薄弱处", "本轮统一后的规则"], [
                ["多个脚本各自写文件", "共用原子存储、摘要与独占运行锁"],
                ["中断可能造成隐性重跑", "先记录尝试；中断保留为失败"],
                ["适配器固定阈值与边界", "严格读取声明的风险阈值和参数框"],
                ["证书测试未进入 CI", "主 CI 加入研究与证书完整性测试"],
            ], [185, 310]))
        if number == "04":
            story.append(Image(str(out / "figures/resolution.png"), width=495, height=232))
            story.append(para("图注：每根柱的分母为 240 个噪声条件；柱上数字为明确判断数。"
                              "两种噪声共享底层实例，统计推断使用 120 个独立实例。数据：analysis.json。", small))
            story.append(PageBreak())
            story += [para("全部比较结果与逐实例方向", section_title)]
            rows = [[g["budget"], LABELS[g["method"]], f'{g["resolved"]}/{g["planned"]}',
                     g["counts"]["unresolved"], f'{g["medianMs"]:.1f}']
                    for g in a["comparisonGroups"]]
            story.append(table(["LP 上限", "方法", "明确判断", "未决", "中位毫秒"], rows, [46, 189, 88, 60, 112]))
            story += [Spacer(1, 14), Image(str(out / "figures/paired-instances.png"), width=495, height=196)]
            story.append(para("主比较 8 次 LP：先平均同一实例内两种噪声的二元判断差值，再统计其方向。"
                              "这张图展示原始配对差值的方向，不是置信区间。", small))
        if number == "05":
            story.append(Image(str(out / "figures/sensitivity.png"), width=495, height=206))
            story.append(para("图注：每档上限的分母为同一批 120 个独立合成实例；"
                              "两图均从零开始。实际生成误差上限为 1，参数框与结构在生成器内正确。", small))
            story.append(PageBreak())
            story.append(para("全部敏感性结果与具体反例", section_title))
            rows = [[g["cap"], g["upperCounts"]["safe"], g["upperCounts"]["risk_witness"],
                     g["upperCounts"]["incompatible"], g["upperCounts"]["unresolved"],
                     g["upperActualFalseSafe"], g["upperTruthExcluded"]] for g in a["sensitivityGroups"]]
            story.append(table(["上限", "安全", "风险", "不相容", "未决", "错误放行", "真值排除"],
                               rows, [45, 60, 60, 70, 60, 100, 100]))
            story += [Spacer(1, 15), para("反例说明", subtitle)]
            examples = d["falseSafeExamples"]
            if examples:
                for example in examples[:5]:
                    story.append(para(
                        f"{example['caseId']}：真实损失 {example['trueRegret']:.4f}，阈值 {example['threshold']:.2f}；"
                        f"名义状态 {example['nominalStatus']}，较宽上限状态 {example['upperStatus']}。"
                        f"名义集合含真值：{example['nominalTruthContained']}；较宽集合含真值：{example['upperTruthContained']}。"))
                story.append(para("全部反例保存在 false-safe-cases.csv 与 diagnostics.json，未挑选删除。", small))
            else:
                story.append(para("本轮主敏感性队列未观察到名义错误放行。零观察不等于总体风险为零；旧已知反例仍单列保留。"))
        if number == "07":
            for i, (text, url) in enumerate(refs, 1):
                story.append(Paragraph(f'{i}. {html.escape(text)}<br/><link href="{url}" color="#235C83">{html.escape(url)}</link>', small))
    def page(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor("#C8D2DC"))
        canvas.line(48, height-40, width-48, height-40)
        canvas.setFont("ReportZH", 8)
        canvas.setFillColor(colors.HexColor("#617083"))
        canvas.drawString(48, 27, "条件证书与合成机制证据  |  不等同于投稿已就绪")
        canvas.drawRightString(width-48, 27, f"{doc.page}")
        canvas.restoreState()
    doc = SimpleDocTemplate(str(out / "研究报告.pdf"), pagesize=A4,
                            leftMargin=48, rightMargin=48, topMargin=55, bottomMargin=48,
                            title="llm4orTT：结构整合与出版级复核研究报告", author="llm4orTT research")
    doc.build(story, onFirstPage=page, onLaterPages=page)


def render_html(out, sections, a, d, refs):
    nav = "".join(f'<a href="#s{n}">{n} {html.escape(h)}</a>' for n, h, _ in sections)
    blocks = []
    for n, heading, paragraphs in sections:
        text = "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
        extra = ""
        if n == "04":
            extra += '<img src="figures/resolution.png" alt="四种方法在三个LP预算下的明确判断比例，分母为240个噪声条件。">'
            extra += '<label for="budget">查看计算预算：</label><select id="budget"><option value="all">全部</option><option value="2">2 次 LP</option><option value="8">8 次 LP</option><option value="32">32 次 LP</option></select>'
            extra += '<div class="scroll"><table id="comparison"><thead><tr><th>LP 上限</th><th>方法</th><th>明确判断</th><th>未决</th><th>中位毫秒</th></tr></thead><tbody>'
            for g in a["comparisonGroups"]:
                extra += f'<tr data-budget="{g["budget"]}"><td>{g["budget"]}</td><td>{LABELS[g["method"]]}</td><td>{g["resolved"]}/{g["planned"]}</td><td>{g["counts"]["unresolved"]}</td><td>{g["medianMs"]:.1f}</td></tr>'
            extra += '</tbody></table></div><img src="figures/paired-instances.png" alt="每类40个实例中，候选与强对照差值的方向。">'
        if n == "05":
            extra += '<img src="figures/sensitivity.png" alt="三个声明上限下，错误放行数与条件安全数，均以120个实例为分母。">'
            extra += '<table><thead><tr><th>上限</th><th>条件安全</th><th>错误放行</th><th>真值排除</th></tr></thead><tbody>'
            for g in a["sensitivityGroups"]:
                extra += f'<tr><td>{g["cap"]}</td><td>{g["rangeSafe"]}/120</td><td>{g["upperActualFalseSafe"]}</td><td>{g["upperTruthExcluded"]}</td></tr>'
            extra += '</tbody></table>'
            for example in d["falseSafeExamples"]:
                extra += f'<details><summary>{html.escape(example["caseId"])}：真实损失 {example["trueRegret"]:.4f}</summary><p>名义 safe → 较宽 {example["upperStatus"]}；阈值 {example["threshold"]:.2f}。<a href="{example["evidence"]}">查看原始双端点证据</a></p></details>'
        if n == "07":
            extra += '<ul>' + ''.join(f'<li><a href="{u}">{html.escape(t)}</a></li>' for t, u in refs) + '</ul>'
            extra += '<div class="files">' + ''.join(f'<a href="{name}">{label}</a>' for name, label in [
                ("研究报告.pdf", "下载 PDF"), ("freeze.json", "冻结协议与源码哈希"),
                ("analysis.json", "全部预定统计"), ("independent-followup-audit.json", "独立精确审计"),
                ("diagnostics.json", "事后机制诊断"), ("comparison-costs.csv", "每次运行资源账"),
            ]) + '</div>'
        blocks.append(f'<section id="s{n}"><span class="index">{n}</span><h2>{heading}</h2>{text}{extra}</section>')
    css = """*{box-sizing:border-box}body{margin:0;color:#26364a;background:#f4f6f8;font:16px/1.9 "Microsoft YaHei",sans-serif}a{color:#245d80}header{background:#152f4b;color:#fff;padding:60px max(6vw,24px)}header p{max-width:800px;color:#d5e1ed}h1{font-size:36px;line-height:1.4;max-width:900px;margin:16px 0}header .tag{letter-spacing:2px;font-size:13px}main{max-width:1180px;margin:0 auto;display:grid;grid-template-columns:225px minmax(0,1fr);gap:36px;padding:32px 24px}nav{position:sticky;top:24px;align-self:start;font-size:13px}nav a{display:block;padding:8px 0;text-decoration:none}article{min-width:0}section{background:#fff;margin-bottom:30px;padding:34px 38px;scroll-margin-top:20px}h2{font-size:24px;line-height:1.5;margin:4px 0 22px}.index{font-size:12px;color:#687c90;letter-spacing:3px}p{margin:0 0 17px}img{display:block;width:100%;height:auto;margin:24px 0}table{width:100%;border-collapse:collapse;font-size:13px;margin:18px 0}th,td{text-align:left;padding:11px 10px;border-bottom:1px solid #dce3ea}th{background:#edf2f6}.scroll{overflow:auto}select{padding:7px;margin:10px;border:1px solid #abbac8;background:white;font:inherit}details{padding:12px 0;border-bottom:1px solid #dce3ea}summary{cursor:pointer;font-size:14px}.files{display:flex;flex-wrap:wrap;gap:14px;font-size:14px}.footer{padding:30px;text-align:center;color:#627589;font-size:13px}@media(max-width:800px){h1{font-size:28px}main{display:block;padding:16px}nav{position:static;margin:8px 0 22px}nav a{display:inline-block;margin-right:14px}section{padding:24px 20px}}@media print{nav,select{display:none}main{display:block}section{break-inside:avoid}header{color:#152f4b;background:white;padding:20px}body{background:white}}"""
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>llm4orTT｜结构整合与研究复核</title><style>'+css+'</style><header><div class="tag">LLM4ORTT 0.1.2 · RESEARCH AUDIT · 2026-10-21</div><h1>可靠性先于漂亮分数</h1><p>2,880 次方法运行 · 360 个双端点档案 · 120 个独立实例 / 队列<br>让每个结论都能找到原始输入、计算记录与独立核验。</p></header><main><nav>'+nav+'</nav><article>'+''.join(blocks)+'</article></main><div class="footer">本地冻结研究；合成证据不等同于真实业务验证或 AAAI 投稿就绪。</div><script>document.getElementById("budget").addEventListener("change",e=>{document.querySelectorAll("#comparison tbody tr").forEach(r=>r.hidden=e.target.value!=="all"&&r.dataset.budget!==e.target.value)})</script></html>'
    (out / "完整研究报告.html").write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
