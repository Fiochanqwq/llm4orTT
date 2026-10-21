"""Zero-call L3 on immutable historical proposals; all writes go to a new batch."""
import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from language_decisions import decide
from language_evaluator import score
from language_io_guard import zero_call_guard
from language_primary_statistics import analyze
from language_stage import create, digest, encoded, read


def oracle_selection(truth):
    selected = sorted(h for h, w in truth["thetaTenths"].items() if w != 0)
    if selected != [truth["activeFactor"]] or any(h in truth["distractors"] for h in selected):
        raise ValueError("L3 must contain exactly the true factor and no distractor")
    return selected


def run(source, target):
    source, target = source.resolve(), target.resolve()
    if not target.is_relative_to((ROOT / "实验").resolve()) or target.exists():
        raise ValueError("Use a fresh output directory inside 实验")
    source_stage = source / "language"
    source_freeze = read(source_stage / "freeze.json")
    if digest((source_stage / "freeze.json").read_bytes()) != (source_stage / "freeze.sha256").read_text("ascii"):
        raise ValueError("Original freeze corrupted")
    entries = [e for e in source_freeze["entries"] if e["phase"] == "instances"]
    if len(entries) != 60:
        raise ValueError("Expected 60 source instances")
    stage = target / "language"
    (stage / "truth").mkdir(parents=True)
    protocol = {
        "schema": "oracle-structure-reanalysis.v1",
        "declaredUTC": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "solePrimaryTest": "L0 A0 vs L1 A0 dangerous-release paired exact two-sided McNemar",
        "selectionTiming": "Primary selected for this reanalysis after the old result was known; not an independent prospective validation.",
        "n": 60, "dangerThreshold": .25, "noiseEndpoints": [0, 1],
        "L3": "True nonzero factor only; do not supply its weight to fitting or audit",
        "dangerDensityTarget": 30, "currentCohort": "Original fixed cohort, no selection or changed inputs",
        "sourceInventorySha256": source_freeze["formalInventorySha256"],
        "budget": {"newModelCalls": 0, "retries": 0},
        "successA": "L1 danger >=30 AND primary discordant >=20 AND p<0.01",
        "successB": "L1 danger >=30 AND L3-minus-L1 A2 availability <=0.10",
        "sources": {name: digest((ROOT / name).read_bytes()) for name in (
            "research/language_oracle_reanalysis.py", "research/language_primary_statistics.py",
            "research/language_decisions.py", "research/language_evaluator.py",
            "research/language_io_guard.py", "solver/inverse.py")},
    }
    create(stage / "analysis-protocol.json", protocol)
    original_hashes = {}
    rows = []
    with zero_call_guard():
        for entry in entries:
            original = source_stage / entry["relativeDirectory"]
            folder = stage / "instances" / entry["id"]
            folder.mkdir(parents=True)
            for name, key in (("input.json", "inputSha256"), ("truth.json", "truthSha256"),
                              ("request.json", "requestSha256"), ("prompt.txt", "promptSha256")):
                data = (original / name).read_bytes()
                if digest(data) != entry[key]:
                    raise ValueError("Old input changed: " + entry["id"] + "/" + name)
                destination = stage / "truth" / (entry["id"] + ".json") if name == "truth.json" else folder / name
                destination.write_bytes(data)
                original_hashes[str(original / name)] = digest(data)
            for name in ("proposal.json", "response.raw.json", "proposed-input.json"):
                data = (original / name).read_bytes()
                (folder / name).write_bytes(data)
                original_hashes[str(original / name)] = digest(data)
            source_call = read(original / "call.json")
            create(folder / "call.json", {
                "status": "reused_historical_response", "newModelCalls": 0, "retries": 0,
                "responseId": source_call["responseId"], "sourceCallPath": str(original / "call.json"),
                "sourceCallSha256": digest((original / "call.json").read_bytes()),
                "note": "No request was sent this round; historical prompt and response copied unchanged.",
            })
            public = read(folder / "input.json")
            truth = read(stage / "truth" / (entry["id"] + ".json"))
            result = copy.deepcopy(read(original / "result.json"))
            selected = oracle_selection(truth)
            decision = decide(public, selected)
            evaluation = score(public, truth, decision)
            if evaluation["structureRecall"] != 1 or evaluation["wrongStructure"] != 0:
                raise ValueError("L3 structure validation failed")
            result["decisions"]["L3"] = decision
            result["scores"]["L3"] = evaluation
            result["L3Validation"] = {"hitsTruth": True, "containsDistractor": False, "newModelCalls": 0}
            result["sourceResultPath"] = str(original / "result.json")
            create(folder / "result.json", result)
            rows.append({k: entry[k] for k in ("id", "domain", "seed")} |
                        {"status": result["status"], "scores": result["scores"],
                         "relativeDirectory": folder.relative_to(stage).as_posix()})
            print(json.dumps({"L3completed": len(rows), "newModelCalls": 0}), flush=True)
        summary = analyze(rows)
        summary["calls"] = {"newModelCalls": 0, "historicalFormalResponsesReused": 60,
                            "L3ModelCalls": 0, "runtimeNetworkAndChildProcessesBlocked": True}
        summary["analysisTiming"] = protocol["selectionTiming"]
        summary["sourceInventorySha256"] = protocol["sourceInventorySha256"]
        summary["oracleStructureValidated"] = {"instances": 60, "recall": 60, "falseFeatures": 0}
        summary["abstract"] = (
            f"In 60 fixed synthetic language instances, LLM-proposed structure reduced dangerous release "
            f"from {summary['primary']['L0']['count']}/60 to {summary['primary']['L1']['count']}/60 "
            f"(discordant {summary['primary']['L0only']}:{summary['primary']['L1only']}, "
            f"exact two-sided McNemar p={summary['primary']['pExactTwoSided']}). "
            f"With oracle structure, two-endpoint auditing yielded "
            f"{summary['arms']['L3']['A2']['availableCorrect']['count']}/60 correct determinate decisions "
            f"and {summary['arms']['L3']['A2']['dangerousReleased']['count']}/60 dangerous releases; "
            f"LLM-structure audit availability was {summary['arms']['L1']['A2']['availableCorrect']['count']}/60."
        )
        create(stage / "summary.json", summary)
        for name, before in original_hashes.items():
            if digest(Path(name).read_bytes()) != before:
                raise ValueError("Historical file was modified: " + name)
        create(stage / "language-stage-audit.json", {**summary["calls"], "status": "complete", "oldInputsUnchanged": True})
    print(json.dumps({k: summary[k] for k in ("primary", "oracleComparison", "density", "success", "calls")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.out)
