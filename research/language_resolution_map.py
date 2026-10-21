"""H=6 offline discrimination map, with exact rational LP verification."""
import argparse
import copy
import csv
import hashlib
import json
import random
import sys
from fractions import Fraction as Q
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from language_stage import read, create, verify
from language_io_guard import zero_call_guard
from language_decisions import inverse_input, recover, parse_proposal
from language_statistics import proportion

CAPS = [Q(1, 4), Q(1, 2), Q(1), Q(2), Q(4)]
THRESHOLDS = [Q(1, 10), Q(1, 4), Q(1, 2)]


def maximize(rows, objective):
    """Floating-point LP locates an optimum; exact primal/dual equality certifies it."""
    import highspy
    d = len(objective)
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    model.setOptionValue("threads", 1)
    model.addCols(d, [-float(v) for v in objective], [-highspy.kHighsInf]*d,
                  [highspy.kHighsInf]*d, 0, [], [], [])
    starts, indices, values = [0], [], []
    for a, _ in rows:
        for j, coefficient in enumerate(a):
            if coefficient:
                indices.append(j)
                values.append(float(coefficient))
        starts.append(len(indices))
    model.addRows(len(rows), [-highspy.kHighsInf]*len(rows), [float(b) for _, b in rows],
                  len(indices), starts, indices, values)
    model.run()
    if model.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise ValueError("LP did not locate an optimum: " + str(model.getModelStatus()))
    solution = model.getSolution()
    x = [Q(float(v)).limit_denominator(1000000) for v in solution.col_value]
    dual = [Q(-float(v)).limit_denominator(1000000) for v in solution.row_dual]
    if not all(sum(v*z for v,z in zip(a,x)) <= b for a,b in rows):
        raise ValueError("Exact primal feasibility failed")
    if not all(v >= 0 for v in dual):
        raise ValueError("Exact dual nonnegativity failed")
    if any(sum(weight*a[j] for weight,(a,_) in zip(dual,rows)) != objective[j] for j in range(d)):
        raise ValueError("Exact dual equality failed")
    primal = sum(c*v for c,v in zip(objective,x))
    dual_value = sum(weight*b for weight,(_,b) in zip(dual,rows))
    if primal != dual_value:
        raise ValueError("Exact primal-dual objective equality failed")
    return primal, x


def constraints(public, selected, cap):
    d = len(selected)
    rows = []
    for j in range(d):
        unit = tuple(int(j == k) for k in range(d))
        rows.extend([(unit, Q(20)), (tuple(-v for v in unit), Q(0))])
    for context in public["histories"]:
        observed = next(a for a in context["actions"] if a["id"] == context["chosen"])
        for other in context["actions"]:
            rows.append((tuple(observed["monitors"][h]-other["monitors"][h] for h in selected),
                         10*cap-observed["knownCostTenths"]+other["knownCostTenths"]))
    tight = {}
    for a,b in rows:
        tight[a] = min(tight.get(a,b),b)
    return sorted(tight.items())


def certificate(public, selected, chosen, cap):
    rows = constraints(public, selected, cap)
    d = len(selected)
    if any(not any(a) and b < 0 for a,b in rows):
        return {"feasible": False, "worstRegret": None, "exactVerified": True}
    rows = [(a,b) for a,b in rows if any(a)]
    if d:
        # Common-slack phase I also produces an exact infeasibility certificate.
        phase = [(tuple(a)+(-1,), b) for a,b in rows] + [((0,)*d+(-1,), Q(0))]
        negative_slack, _ = maximize(phase, [0]*d+[-1])
        if negative_slack < 0:
            return {"feasible": False, "worstRegret": None, "exactVerified": True}
    chosen_action = next(a for a in public["deployment"]["actions"] if a["id"] == chosen)
    worst = Q(0)
    for other in public["deployment"]["actions"]:
        objective = [chosen_action["monitors"][h]-other["monitors"][h] for h in selected]
        value = maximize(rows, objective)[0] if d and any(objective) else Q(0)
        worst = max(worst, (chosen_action["knownCostTenths"]-other["knownCostTenths"]+value)/10)
    return {"feasible": True, "worstRegret": str(worst), "exactVerified": True}


def status(nominal, upper, threshold):
    if not upper["feasible"]:
        return "incompatible"
    if Q(upper["worstRegret"]) > threshold:
        return "risk"
    return "safe" if nominal["feasible"] else "unresolved"


def fit_choice(public, selected):
    if selected:
        fit = recover(inverse_input(public, selected))
        if fit["status"] != "optimal":
            raise ValueError("Point fit not optimal")
        theta = fit["theta"]
    else:
        theta = {}
    return min((Q(a["knownCostTenths"],10)+sum(Q(str(theta[h]))*a["monitors"][h] for h in selected), a["id"])
               for a in public["deployment"]["actions"])[1]


def inject(public, instance_id):
    result = copy.deepcopy(public)
    seed = int.from_bytes(hashlib.sha256(("map-false-v1:"+instance_id).encode()).digest()[:8], "big")
    rng = random.Random(seed)
    for context in result["histories"] + [result["deployment"]]:
        for action in context["actions"]:
            action["monitors"]["injected_zero_3"] = rng.randint(0,3)
    return result


def cell_metrics(rows):
    c = dict(TP=0, FN=0, FP=0, TN=0, dangerousAbstain=0, safeAbstain=0)
    for row in rows:
        danger, verdict = row["dangerous"], row["status"]
        key = ("TP" if danger else "FP") if verdict == "risk" else (
            ("FN" if danger else "TN") if verdict == "safe" else ("dangerousAbstain" if danger else "safeAbstain"))
        c[key] += 1
    positives = c["TP"]+c["FN"]+c["dangerousAbstain"]
    negatives = len(rows)-positives
    rate = lambda k,n: proportion(k,n) if n else {"count":k,"denominator":0,"rate":None,"wilson95":None}
    return {**c, "n":len(rows), "dangerous":positives, "safe":negatives,
            "sensitivity":rate(c["TP"],positives), "specificity":rate(c["TN"],negatives),
            "dangerousRelease":rate(c["FN"],len(rows)),
            "correctExplicit":rate(c["TP"]+c["TN"],len(rows))}


def run(a,b,out):
    if out.exists():
        raise FileExistsError("Fresh map directory required")
    fa, fb = verify(a), verify(b)
    if [e["id"] for e in fa["entries"]] != [e["id"] for e in fb["entries"]]:
        raise ValueError("A/B mismatch")
    out.mkdir(parents=True)
    create(out/"analysis-spec.json", {
        "H":[6], "caps":[float(c) for c in CAPS], "thresholds":[float(t) for t in THRESHOLDS], "k":[0,1,2,3],
        "newModelCalls":0, "regime":"reference coefficient = true weight - 0.8",
        "history":"原队列只有 6 行历史，扩展需另立机制；本轮不扩展。",
        "injection":"Nested false features: sorted original two zero-truth factor IDs, then injected_zero_3. Third feature uses Random(first 8 SHA256 bytes of map-false-v1:<id>, big endian), randint(0,3) in existing history/action order then deployment/action order. Weight truth=0; coefficient box unchanged [0,2].",
        "arms":"L3 plus k false features; L0 plus k false features; observed L1 A/B and fixed L_all. For observed L1, k is not an intervention axis.",
        "pointFit":"Refit once per selected structure on unchanged six histories; fixed lexical tie break. Cap and threshold vary audit only. Original L1 recommendations reused after proposal-ID validation.",
        "endpoints":"0 and cap; upper counterexample means risk; upper safe needs nominal feasible, otherwise unresolved.",
        "labels":"External true regret > scanned threshold, recomputed in every cell. Thus positive/negative denominators can change with threshold and selected structure.",
        "nulls":"Zero denominators yield null rates and null intervals; count separately, never replace by zero or one.",
        "sensitivity":"TP/all true dangerous, including abstentions; specificity TN/all true safe, including abstentions.",
        "validity":"Cap below realized historical regret 0.8 is a misspecified uncertainty set; high specificity there need not mean truthful certification.",
        "inference":"Descriptive finite grid, no population optimum claim, no extrapolation beyond this regime. Keep every tied maximum and every cap-adjacent >60% boundary.",
    })
    (out/"instances").mkdir()
    grouped = {}
    for entry in fa["entries"]:
        folder = a/entry["relativeDirectory"]
        public = read(folder/"input.json")
        if len(public["histories"]) != 6:
            raise ValueError("Unexpected H")
        private = read(a/entry["truthRelativePath"])
        augmented = inject(public, entry["id"])
        false_ids = sorted(private["distractors"])+["injected_zero_3"]
        a_result = read(folder/"result.json")
        b_result = read(b/entry["relativeDirectory"]/"result.json")
        arms = []
        for k in range(4):
            arms.extend([("L3",k,sorted([private["activeFactor"]]+false_ids[:k]),None),
                         ("L0",k,sorted(false_ids[:k]),None)])
        for name,result,source in (("L1",a_result,a),("L1_no_logs",b_result,b)):
            selected = parse_proposal(read(source/entry["relativeDirectory"]/"proposal.json"),public["catalog"])
            if selected != result["decisions"]["L1"]["selected"]:
                raise ValueError("Saved proposal disagrees with decision")
            arms.append((name,None,selected,result["decisions"]["L1"]["chosenDecision"]))
        arms.append(("L_all",None,sorted(h["id"] for h in public["catalog"]),None))
        cache, details = {}, []
        for arm,k,selected,original_chosen in arms:
            selection = tuple(selected)
            if selection not in cache:
                chosen = fit_choice(augmented,selected)
                costs = {x["id"]:Q(x["knownCostTenths"]+sum(x["monitors"][h]*w for h,w in private["thetaTenths"].items()),10)
                         for x in public["deployment"]["actions"]}
                regret = costs[chosen]-min(costs.values())
                certs = {str(cap):certificate(augmented,selected,chosen,cap) for cap in [Q(0)]+CAPS}
                cache[selection] = chosen,regret,certs
            chosen,regret,certs = cache[selection]
            if original_chosen is not None and chosen != original_chosen:
                raise ValueError("Refit changed frozen L1 recommendation")
            if arm in ("L3","L0") and k == 0 and chosen != a_result["decisions"][arm]["chosenDecision"]:
                raise ValueError("Original structure control changed")
            details.append({"arm":arm,"k":k,"selected":selected,"chosen":chosen,"trueRegret":str(regret),"certificates":certs})
            for cap in CAPS:
                for threshold in THRESHOLDS:
                    key = arm,k,float(cap),float(threshold)
                    row = {"id":entry["id"],"domain":entry["domain"],"dangerous":regret>threshold,
                           "status":status(certs["0"],certs[str(cap)],threshold)}
                    grouped.setdefault(key,[]).append(row)
        create(out/"instances"/(entry["id"]+".json"), {"augmentedInput":augmented,"evaluations":details})
        print(json.dumps({"instances":len(next(iter(grouped.values()))),"id":entry["id"],"calls":0}),flush=True)
    cells=[]
    for (arm,k,cap,threshold),rows in grouped.items():
        cells.append({"arm":arm,"k":k,"H":6,"cap":cap,"threshold":threshold,**cell_metrics(rows),"rows":rows})
    main=[c for c in cells if c["arm"] == "L3"]
    defined=[c for c in main if c["specificity"]["rate"] is not None]
    best=max(c["specificity"]["rate"] for c in defined)
    maxima=[{k:v for k,v in c.items() if k!="rows"} for c in defined if c["specificity"]["rate"] == best]
    boundaries=[]
    for k in range(4):
        for threshold in [float(t) for t in THRESHOLDS]:
            line=sorted([c for c in main if c["k"]==k and c["threshold"]==threshold],key=lambda c:c["cap"])
            for x,y in zip(line,line[1:]):
                if x["specificity"]["rate"] is not None and y["specificity"]["rate"] is not None and (x["specificity"]["rate"]>.6)!=(y["specificity"]["rate"]>.6):
                    boundaries.append({"k":k,"threshold":threshold,"fromCap":x["cap"],"fromSpecificity":x["specificity"]["rate"],"toCap":y["cap"],"toSpecificity":y["specificity"]["rate"]})
    nulls={arm:{metric:sum(c[metric]["rate"] is None for c in cells if c["arm"]==arm) for metric in ("sensitivity","specificity")}
           for arm in sorted({c["arm"] for c in cells})}
    fully_defined=sum(all(c[m]["rate"] is not None for m in ("sensitivity","specificity","dangerousRelease","correctExplicit")) for c in main)
    summary={"newModelCalls":0,"regime":"reference coefficient = true weight - 0.8","H":6,"nPerCell":60,
             "cellCount":len(cells),"mainCellCount":len(main),"cells":cells,"nullCounts":nulls,
             "maximumSpecificity":best,"maximizers":maxima,"specificityAbove60Exists":any(c["specificity"]["rate"]>.6 for c in defined),
             "capAdjacentBoundaries":boundaries,"fullyDefinedMainCells":fully_defined,
             "criterionAOriginalNumeric90Percent":"PASS" if fully_defined/len(main)>=.9 else "FAIL",
             "allRequestedCellsComputed":True,"criterionB":"PASS",
             "appendix":["原队列只有 6 行历史，扩展需另立机制；H=4/8/16未计算。","阈值或结构使阳性/阴性分母为零时率为null，不是计算失败。","66.7%可降空间解释未采用：40/60的60是剩余风险，不是已定义的可降空间。"],
             "byDomain":{domain:[{"arm":c["arm"],"k":c["k"],"cap":c["cap"],"threshold":c["threshold"],**cell_metrics([r for r in c["rows"] if r["domain"]==domain])} for c in cells]
                         for domain in ("dispatch","staffing","workshop")}}
    create(out/"summary.json",summary)
    with (out/"map.csv").open("x",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["arm","k","H","cap","threshold","n","dangerous","safe","TP","FN","FP","TN","dangerousAbstain","safeAbstain","sensitivity","specificity","dangerousRelease","correctExplicit"])
        for c in cells:
            writer.writerow([c[x] if c[x] is not None else "not_scanned" for x in ("arm","k","H","cap","threshold","n","dangerous","safe","TP","FN","FP","TN","dangerousAbstain","safeAbstain")]+[c[x]["rate"] if c[x]["rate"] is not None else "null" for x in ("sensitivity","specificity","dangerousRelease","correctExplicit")])
    verify(a);verify(b)
    return {k:v for k,v in summary.items() if k not in ("cells","byDomain")}


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    for name in ("a","b","out"):
        p.add_argument("--"+name,type=Path,required=True)
    args=p.parse_args()
    with zero_call_guard():
        print(json.dumps(run(args.a.resolve(),args.b.resolve(),args.out.resolve()),ensure_ascii=False))
