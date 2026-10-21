"""Prospective paired comparison. All original and failed runs are retained."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from comparison_cases import make_case, prepare_problem
from certificate_methods import run_method
from verify_comparison import prepare_case, verify_prepared
from experiment_runtime import save, sha


def descriptors(protocol):
    cases = []
    for split, key in [("development", "development_seeds"), ("evaluation", "evaluation_seeds"),
                       ("misspecification", "misspecification_seeds")]:
        for family in protocol["families"]:
            for seed in protocol[key]:
                noises = protocol["noise_absolute"] if split != "misspecification" else [protocol["misspecification_actual_noise"]]
                for actual in noises:
                    declared = actual if split != "misspecification" else protocol["misspecification_declared_noise"]
                    cases.append({"id": f"{split}-{family}-s{seed}-n{actual}", "split": split,
                                  "family": family, "seed": seed, "actualNoise": actual, "declaredNoise": declared})
    return cases


def freeze(output, protocol):
    paths = ["research/experiment_runtime.py", "research/comparison_protocol.json", "research/comparison_cases.py", "research/certificate_methods.py",
             "research/run_comparison.py", "research/analyze_comparison.py", "research/verify_comparison.py",
             "solver/inverse_certified.py", "solver/inverse.py"]
    hashes = {path: sha(ROOT / path) for path in paths}
    freeze_path = output / "freeze.json"
    if freeze_path.exists():
        previous = json.loads(freeze_path.read_text("utf-8"))
        if hashes != previous["sourceHashes"]:
            raise RuntimeError("Frozen source changed. Keep old results and choose a new output directory.")
        return previous["schedule"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "cases").mkdir(exist_ok=True)
    (output / "runs").mkdir(exist_ok=True)
    (output / "frozen-source").mkdir(exist_ok=True)
    schedule = []
    ordering = random.Random(protocol["run_order_seed"])
    for case in descriptors(protocol):
        for budget in protocol["lp_budgets"]:
            methods = list(protocol["methods"])
            ordering.shuffle(methods)
            for method in methods:
                schedule.append({"caseId": case["id"], "method": method, "budget": budget, "split": case["split"]})
    for path in paths:
        target = output / "frozen-source" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    value = {"schema": "certificate-comparison-freeze.v1", "createdUTC": datetime.now(timezone.utc).isoformat(),
             "localProspectiveFreeze": True, "publicRegistryRegistration": False, "protocol": protocol,
             "sourceHashes": hashes, "schedule": schedule,
             "runtime": {"python": sys.version, "platform": platform.platform(),
                         "highspy": importlib.metadata.version("highspy"),
                         "pyomo": importlib.metadata.version("pyomo"),
                         "numpy": importlib.metadata.version("numpy")}}
    save(freeze_path, value)
    return schedule


def normalize_result(result, case):
    ids = [h["id"] for h in case["input"]["hypotheses"]]
    normalized = dict(result)
    normalized["chosenDecision"] = case["chosenDecision"]
    normalized["threshold"] = case["input"]["certification"]["threshold"]
    from fractions import Fraction
    normalized["thresholdRational"] = str(Fraction(str(normalized["threshold"])))
    normalized["witnesses"] = [w if isinstance(w, dict) else dict(zip(ids, w))
                               for w in result.get("witnesses", [])]
    return normalized


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "evaluation", "misspecification", "all"], required=True)
    parser.add_argument("--out", default="outputs/comparison-20261020")
    args = parser.parse_args()
    output = ROOT / args.out
    protocol = json.loads((ROOT / "research/comparison_protocol.json").read_text("utf-8"))
    schedule = freeze(output, protocol)
    selected_cases = [case for case in descriptors(protocol) if args.split in ("all", case["split"])]
    failures = 0
    for index, desc in enumerate(selected_cases):
        case_path = output / "cases" / (desc["id"] + ".json")
        if case_path.exists():
            raise RuntimeError("Refusing to overwrite a case; a rerun must use a new output directory: " + str(case_path))
        started = time.monotonic()
        case, tables = make_case(desc["family"], desc["seed"], desc["actualNoise"], desc["declaredNoise"], desc["split"])
        case["id"] = desc["id"]
        case["generatorMs"] = (time.monotonic() - started) * 1000
        prep_error = None
        try:
            problem = prepare_problem(case, tables)
            prepared_audit = prepare_case(case["input"], case["chosenDecision"], case["truth"])
        except Exception as error:
            prep_error = repr(error)
            case["preprocessingFailure"] = prep_error
        save(case_path, case)
        counts = {}
        for planned in [p for p in schedule if p["caseId"] == desc["id"]]:
            method, budget = planned["method"], planned["budget"]
            record = {**planned, "caseSha256": sha(case_path), "executionStatus": "failed"}
            run_started = time.monotonic()
            try:
                if prep_error:
                    raise RuntimeError("Shared preprocessing failed: " + prep_error)
                result = run_method(problem, method, budget, protocol["method_wall_seconds"])
                record["result"] = normalize_result(result, case)
                record["verification"] = verify_prepared(prepared_audit, record["result"])
                record["executionStatus"] = "complete"
                counts[result["status"]] = counts.get(result["status"], 0) + 1
            except Exception as error:
                record["error"] = repr(error)
                failures += 1
                counts["failed"] = counts.get("failed", 0) + 1
            record["includingVerificationMs"] = (time.monotonic() - run_started) * 1000
            save(output / "runs" / f"{desc['id']}__{method}__b{budget}.json", record)
        save(output / ("progress-" + args.split + ".json"),
             {"completedCases": index + 1, "plannedCases": len(selected_cases), "failedRuns": failures,
              "lastCase": desc["id"], "lastCaseCounts": counts})
        if index % 3 == 0 or index + 1 == len(selected_cases):
            print(json.dumps({"split": args.split, "completedCases": index + 1, "of": len(selected_cases),
                              "failedRuns": failures, "lastCaseCounts": counts}), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
