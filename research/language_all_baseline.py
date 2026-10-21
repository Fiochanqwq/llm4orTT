"""Recompute fixed-all-candidate structure without credentials or model calls."""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from language_stage import read, create, digest
from language_decisions import decide
from language_evaluator import score
from language_io_guard import zero_call_guard
from language_ablation import confusion
from language_primary_statistics import comparison
from language_statistics import proportion


def run(a, b, out):
    if out.exists():
        raise FileExistsError("Use a fresh output directory")
    out.mkdir(parents=True)
    freeze = read(a / "freeze.json")
    rows = []
    for entry in freeze["entries"]:
        folder = a / entry["relativeDirectory"]
        public = read(folder / "input.json")
        truth = read(a / entry["truthRelativePath"])
        if digest((folder / "input.json").read_bytes()) != entry["inputSha256"]:
            raise ValueError("Source input changed")
        selected = sorted(h["id"] for h in public["catalog"])
        decision = decide(public, selected)
        result = score(public, truth, decision)
        result_a = read(folder / "result.json")
        result_b = read(b / entry["relativeDirectory"] / "result.json")
        rows.append({"id": entry["id"], "domain": entry["domain"],
                     "historyRows": len(public["histories"]),
                     "scores": {"L_all": result, "L1": result_a["scores"]["L1"],
                                "L1_no_logs": result_b["scores"]["L1"]},
                     "decision": decision,
                     "sameChosenDecisionAsL1": decision["chosenDecision"] == result_a["decisions"]["L1"]["chosenDecision"],
                     "sameSelectedStructureAsL1": selected == result_a["decisions"]["L1"]["selected"]})
        print(json.dumps({"completed": len(rows), "id": entry["id"], "modelCalls": 0}), flush=True)
    def metric(row, structure, audit, name):
        return row["scores"][structure]["arms"][audit][name]
    contrasts = {}
    for other in ("L1", "L1_no_logs"):
        contrasts[other] = {}
        for audit, name in (("A0", "dangerousReleased"), ("A2", "dangerousReleased"), ("A2", "availableCorrect")):
            contrasts[other][audit + "_" + name] = comparison(
                [metric(r, "L_all", audit, name) for r in rows],
                [metric(r, other, audit, name) for r in rows], "L_all", other)
    summary = {
        "n": 60, "newModelCalls": 0, "runtimeNetworkAndChildProcessesBlocked": True,
        "sourceA": str(a), "sourceB": str(b), "cap": 1, "threshold": .25,
        "historyRows": 6, "regime": "reference coefficient = true weight - 0.8",
        "arms": {s: {"A0DangerousRelease": proportion(sum(metric(r, s, "A0", "dangerousReleased") for r in rows)),
                      "A2DangerousRelease": proportion(sum(metric(r, s, "A2", "dangerousReleased") for r in rows)),
                      "A2CorrectExplicit": proportion(sum(metric(r, s, "A2", "availableCorrect") for r in rows)),
                      "confusion": confusion(rows, s)} for s in ("L_all", "L1", "L1_no_logs")},
        "paired": contrasts,
        "sameChosenDecisionAsL1": sum(r["sameChosenDecisionAsL1"] for r in rows),
        "sameSelectedStructureAsL1": sum(r["sameSelectedStructureAsL1"] for r in rows),
        "rows": rows,
    }
    create(out / "baseline.json", summary)
    with (out / "baseline.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["structure", "n", "A0_dangerous_release", "A2_TP", "A2_FN", "A2_FP", "A2_TN", "sensitivity", "specificity", "correct_explicit"])
        for s, value in summary["arms"].items():
            matrix = value["confusion"]
            writer.writerow([s, 60, value["A0DangerousRelease"]["count"], *[matrix[k] for k in ("TP", "FN", "FP", "TN")], matrix["sensitivity"]["rate"], matrix["specificity"]["rate"], value["A2CorrectExplicit"]["count"]])
    return {k: v for k, v in summary.items() if k != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for arg in ("a", "b", "out"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    with zero_call_guard():
        print(json.dumps(run(args.a.resolve(), args.b.resolve(), args.out.resolve()), ensure_ascii=False))
