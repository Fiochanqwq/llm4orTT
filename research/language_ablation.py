"""Prespecified paired logs-only ablation; never sends a model request."""
import argparse
import copy
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from language_stage import ROOT, create, digest, encoded, read, verify, verify_prompt
from language_io_guard import prompt_io_guard, zero_call_guard
from language_primary_statistics import comparison
from language_statistics import proportion


def without_logs(request):
    """Change exactly one JSON field, with all filesystem reads forbidden."""
    with prompt_io_guard():
        changed = copy.deepcopy(request)
        message = changed["messages"][1]["content"]
        prefix, payload = message.split("\n", 1)
        task = json.loads(payload)
        del task["logs"]
        changed["messages"][1]["content"] = prefix + "\n" + encoded(task)
        return changed


def assert_paired_requests(a, b):
    if without_logs(a) != b:
        raise ValueError("B request must differ from A only by deleting logs")


def prepare(a, b):
    original = verify(a)
    if b.exists():
        raise FileExistsError("B requires a fresh directory")
    if any((a / e["relativeDirectory"] / "call.started.json").exists() for e in original["entries"]):
        raise ValueError("Analysis spec must be frozen before A starts")
    b.mkdir(parents=True)
    (b / "truth").mkdir()
    freeze = copy.deepcopy(original)
    freeze["schema"] = "language-logs-ablation-freeze.v1"
    freeze["createdUTC"] = datetime.now(timezone.utc).isoformat()
    freeze["pairedSource"] = str(a)
    freeze["pairedSourceFreezeSha256"] = digest((a / "freeze.json").read_bytes())
    freeze["design"]["textAblation"] = "Delete logs field only; identical instance order, truth, input, monitors, settings and system message."
    freeze["promptTransformation"] = "Parse task_json and delete logs; add no replacement text. System and user templates unchanged."
    freeze["sourceHashes"]["research/language_ablation.py"] = digest(Path(__file__).read_bytes())
    for entry in freeze["entries"]:
        src, dst = a / entry["relativeDirectory"], b / entry["relativeDirectory"]
        dst.mkdir(parents=True)
        shutil.copyfile(src / "input.json", dst / "input.json")
        shutil.copyfile(a / entry["truthRelativePath"], b / entry["truthRelativePath"])
        try:
            request = without_logs(read(src / "request.json"))
        except Exception as error:
            # No substitute text and no replacement instance.
            create(dst / "construction.failure.json", {"status": "unavailable", "error": str(error)})
            raise ValueError("Unconstructible ablation; retain instance and failure, do not launch invalid request") from error
        assert_paired_requests(read(src / "request.json"), request)
        verify_prompt(read(dst / "input.json"), request)
        create(dst / "request.json", request)
        (dst / "prompt.txt").write_text(encoded(request["messages"]), encoding="utf-8", newline="\n")
        entry["requestSha256"] = digest((dst / "request.json").read_bytes())
        entry["promptSha256"] = digest((dst / "prompt.txt").read_bytes())
    freeze["formalInventorySha256"] = digest(encoded(freeze["entries"]))
    freeze["allEntriesSha256"] = digest(encoded(freeze["entries"]))
    create(b / "freeze.json", freeze)
    (b / "freeze.sha256").write_text(digest((b / "freeze.json").read_bytes()), encoding="ascii")
    spec = {
        "createdUTC": datetime.now(timezone.utc).isoformat(),
        "A": str(a), "B": str(b), "n": 60,
        "freezeHashes": {"A": digest((a / "freeze.json").read_bytes()), "B": digest((b / "freeze.json").read_bytes())},
        "budget": {"A": 60, "B": 60, "total": 120, "retries": 0, "wallSeconds": 5400},
        "regime": "History reference coefficient = true weight - 0.8 is injected bias. Estimand differs from the old n60 cohort; no pooling, continuous comparison, or density-only reinterpretation.",
        "solePrimary": "A L0-A0 vs L1-A0 dangerous release. Exact two-sided conditional McNemar, instance-matched.",
        "denominators": "Dangerous release and correct explicit availability divide by 60; missing/failed/unresolved yield zero successes. No removal or replacement.",
        "confusion": {
            "population": "A L1 recommended decisions; danger = external true regret > 0.25.",
            "positive": "A2 status risk", "negative": "A2 status safe",
            "abstention": "unresolved/incompatible are neither safe nor risk; report dangerous and safe abstentions separately",
            "sensitivity": "TP / all known-dangerous decisions, including abstentions in denominator",
            "specificity": "TN / all known-safe decisions, including abstentions in denominator",
            "missingTruthOutcome": "If no L1 recommendation exists, keep missing count in /60 reporting, report unknown base-rate cases; do not invent TP/FN/FP/TN.",
            "conditionalDiagnostics": "Also report TP/(TP+FN), TN/(TN+FP) among explicit decisions; zero denominator is null.",
        },
        "attribution": "L0 omitted cost; L3 supplied true structure with weight refit; L1 model-selected structure. L0-L3 is oracle cost-completion gain, L0-L1 is realized model-proposal gain, L3-L1 is model-specific excess release relative to oracle. Do not confuse L0-L1 with causal text contribution.",
        "oracleAvailability": "A L3 minus L1 A2 correct availability, percentage points; paired two-sided exact McNemar.",
        "ablation": "B L1-A0 vs A L1-A0 dangerous release, same ordered IDs. Discordance B-only:A-only; exact two-sided McNemar. p>=0.05 means no observed effect, not proven equivalence.",
        "intervals": "Wilson 95% for proportions with nonzero denominator.",
        "criteria": {
            "A": "Primary discordant count >=20 AND p<0.01",
            "B": "Observed L3-minus-L1 A2 availability <=10 percentage points",
            "C": "All 60 IDs paired; finite paired difference and exact p, regardless of sign/significance",
        },
        "symmetry": "Reverse sign is reported with identical tests, intervals and PASS/FAIL criteria, without deleting any arm.",
        "execution": "A then B, original order in each. Record returned model/fingerprint; batch order may confound temporal service drift.",
    }
    create(b.parent / "analysis-spec.json", spec)
    (b.parent / "analysis-spec.sha256").write_text(digest((b.parent / "analysis-spec.json").read_bytes()), encoding="ascii")
    return {"status": "frozen", "A": str(a), "B": str(b), "plannedCalls": 120}


def rate(k, n):
    return proportion(k, n) if n else {"count": k, "denominator": n, "rate": None, "wilson95": None}


def confusion(rows, structure="L1"):
    counts = dict(TP=0, FN=0, FP=0, TN=0, dangerousAbstain=0, safeAbstain=0, missing=0)
    for row in rows:
        score = row.get("scores", {}).get(structure)
        if not score:
            counts["missing"] += 1
            continue
        danger = score["dangerous"]
        status = score["arms"]["A2"]["status"]
        key = ("TP" if danger else "FP") if status == "risk" else (
            ("FN" if danger else "TN") if status == "safe" else ("dangerousAbstain" if danger else "safeAbstain"))
        counts[key] += 1
    danger = counts["TP"] + counts["FN"] + counts["dangerousAbstain"]
    safe = counts["FP"] + counts["TN"] + counts["safeAbstain"]
    return {
        **counts, "baseRate": rate(danger, 60), "knownSafe": safe,
        "sensitivity": rate(counts["TP"], danger), "specificity": rate(counts["TN"], safe),
        "explicitOnlySensitivity": rate(counts["TP"], counts["TP"] + counts["FN"]),
        "explicitOnlySpecificity": rate(counts["TN"], counts["TN"] + counts["FP"]),
    }


def metric(row, structure="L1", audit="A0", name="dangerousReleased"):
    return row.get("scores", {}).get(structure, {}).get("arms", {}).get(audit, {}).get(name, 0)


def finish(a, b):
    spec_path = b.parent / "analysis-spec.json"
    spec = read(spec_path)
    if digest(spec_path.read_bytes()) != spec_path.with_suffix(".sha256").read_text("ascii"):
        raise ValueError("Analysis spec changed")
    fa, fb = verify(a), verify(b)
    for label, folder in (("A", a), ("B", b)):
        if digest((folder / "freeze.json").read_bytes()) != spec["freezeHashes"][label]:
            raise ValueError("Freeze changed since analysis specification")
    sa, sb = read(a / "summary.json"), read(b / "summary.json")
    aa, bb = sa["rows"], sb["rows"]
    if [r["id"] for r in aa] != [r["id"] for r in bb] or len(aa) != 60:
        raise ValueError("All 60 ordered IDs must pair")
    for ea, eb in zip(fa["entries"], fb["entries"]):
        if any(ea[k] != eb[k] for k in ("id", "seed", "domain", "inputSha256", "truthSha256")):
            raise ValueError("A/B instance or truth mismatch")
        assert_paired_requests(read(a / ea["relativeDirectory"] / "request.json"),
                               read(b / eb["relativeDirectory"] / "request.json"))
    ablation = comparison([metric(r) for r in bb], [metric(r) for r in aa], "noLogs", "logs")
    ablation.update(noLogs=sb["arms"]["L1"]["A0"]["dangerousReleased"],
                    logs=sa["arms"]["L1"]["A0"]["dangerousReleased"])
    p = ablation["pExactTwoSided"]
    diff = ablation["differenceSecondMinusFirst"]
    ablation["conclusion"] = ("未观察到日志文本改变危险放行率；这不是等效性证明。" if p >= .05 else
                             "日志文本降低危险放行，承担决策相关信息。" if diff < 0 else
                             "日志文本提高危险放行，产生有害的决策影响。")
    primary, oracle = sa["primary"], sa["oracleComparison"]
    attribution = {}
    for structure in ("L0", "L3", "L1"):
        attribution[structure] = {
            "A0": sa["arms"][structure]["A0"], "A2": sa["arms"][structure]["A2"],
            "structureRecall": proportion(sum(r["scores"].get(structure, {}).get("structureRecall", 0) for r in aa)),
            "wrongStructure": proportion(sum(r["scores"].get(structure, {}).get("wrongStructure", 0) for r in aa)),
        }
    bad = lambda s: sa["arms"][s]["A0"]["dangerousReleased"]["rate"]
    attribution["contrastsPP"] = {
        "oracleCostCompletionGainL0minusL3": 100 * (bad("L0") - bad("L3")),
        "realizedModelGainL0minusL1": 100 * (bad("L0") - bad("L1")),
        "modelGainBeyondOracleL3minusL1": 100 * (bad("L3") - bad("L1")),
    }
    result = {
        "n": 60, "analysisSpec": str(spec_path), "regime": spec["regime"],
        "table1Primary": primary, "table2Attribution": attribution,
        "table3Audit": {"L1": confusion(aa), "L3": confusion(aa, "L3"), "availability": oracle},
        "table4TextAblation": ablation,
        "criteria": {
            "A": "PASS" if primary["discordant"] >= 20 and primary["pExactTwoSided"] < .01 else "FAIL",
            "B": "PASS" if oracle["differenceL3minusL1"] <= .10 + 1e-12 else "FAIL",
            "C": "PASS",
        },
        "calls": {"A": sa["calls"], "B": sb["calls"], "newModelCalls": sa["calls"]["newModelCalls"] + sb["calls"]["newModelCalls"], "retries": 0},
        "completed": {"A": sa["completed"], "B": sb["completed"]},
        "byDomain": {d: {
            "A": sa["byDomain"][d], "B": sb["byDomain"][d],
            "ablation": comparison([metric(r) for r in bb if r["domain"] == d],
                                   [metric(r) for r in aa if r["domain"] == d], "noLogs", "logs"),
        } for d in sa["byDomain"]},
        "pairs": [{"id": x["id"], "domain": x["domain"], "A": x, "B": y} for x, y in zip(aa, bb)],
    }
    create(b.parent / "summary.json", result)
    return {k: result[k] for k in ("n", "table1Primary", "table3Audit", "table4TextAblation", "criteria", "calls")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "finish"))
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    args = parser.parse_args()
    with zero_call_guard():
        print(json.dumps((prepare if args.mode == "prepare" else finish)(args.a.resolve(), args.b.resolve()), ensure_ascii=False))
