"""New, frozen follow-up experiments; no replacement of previous observations."""
import argparse
import copy
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
sys.path.insert(0, str(ROOT / "solver"))
from certificate_methods_v2 import run_method_v2
from comparison_cases import make_case, prepare_problem
from inverse_sensitivity import analyze_with_sensitivity
from run_comparison import normalize_result
from verify_comparison import prepare_case, verify_prepared
from experiment_runtime import save, sha


def case_id(phase, family, seed, noise):
    return f"{phase}-{family}-s{seed}-n{noise}"


def freeze(out, protocol):
    sources = [
        "research/experiment_runtime.py",
        "research/followup_protocol.json", "research/run_followup.py",
        "research/analyze_followup.py", "research/verify_followup.py",
        "research/comparison_cases.py", "research/certificate_methods.py",
        "research/certificate_methods_v2.py", "research/run_comparison.py",
        "research/verify_comparison.py", "solver/inverse.py",
        "solver/inverse_certified.py", "solver/inverse_sensitivity.py",
    ]
    hashes = {name: sha(ROOT / name) for name in sources}
    if (out / "freeze.json").exists():
        previous = json.loads((out / "freeze.json").read_text("utf-8"))
        if previous["sourceHashes"] != hashes:
            raise RuntimeError("Frozen source changed; use a new output directory and preserve old results")
        return previous
    out.mkdir(parents=True, exist_ok=True)
    for directory in ("comparison/cases", "comparison/runs", "sensitivity/cases",
                      "sensitivity/profiles", "regression", "frozen-source"):
        (out / directory).mkdir(parents=True, exist_ok=True)
    for name in sources:
        target = out / "frozen-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    rng = random.Random(protocol["run_order_seed"])
    comparisons, profiles = [], []
    for family in protocol["families"]:
        for seed in protocol["comparison_seeds"]:
            for noise in protocol["comparison_noise"]:
                identifier = case_id("comparison", family, seed, noise)
                for budget in protocol["lp_budgets"]:
                    methods = protocol["methods"].copy()
                    rng.shuffle(methods)
                    comparisons.extend({"caseId": identifier, "method": m, "budget": budget}
                                       for m in methods)
        for seed in protocol["sensitivity_seeds"]:
            identifier = case_id("sensitivity", family, seed, protocol["sensitivity_actual_noise"])
            caps = protocol["sensitivity_caps"].copy()
            rng.shuffle(caps)
            profiles.extend({"caseId": identifier, "cap": cap} for cap in caps)
    frozen = {
        "schema": "inverse-followup-freeze.v1", "createdUTC": datetime.now(timezone.utc).isoformat(),
        "protocol": protocol, "sourceHashes": hashes,
        "comparisonSchedule": comparisons, "sensitivitySchedule": profiles,
        "runtime": {"python": sys.version, "platform": platform.platform(),
                    **{name: importlib.metadata.version(name) for name in ("highspy", "numpy", "pyomo")}},
    }
    save(out / "freeze.json", frozen)
    return frozen


def build_case(family, seed, actual, declared, phase, directory):
    identifier = case_id(phase, family, seed, actual)
    path = directory / "cases" / (identifier + ".json")
    if path.exists():
        raise RuntimeError("Refusing to overwrite existing case: " + identifier)
    tick = time.monotonic()
    case, tables = make_case(family, seed, actual, declared, phase)
    case["id"] = identifier
    case["generatorMs"] = (time.monotonic() - tick) * 1000
    problem, error = None, None
    try:
        problem = prepare_problem(case, tables)
    except Exception as exc:
        error = repr(exc)
        case["preprocessingFailure"] = error
    save(path, case)
    return case, problem, error, sha(path)


def comparison(out, frozen):
    p = frozen["protocol"]
    directory = out / "comparison"
    count, failures = 0, 0
    for family in p["families"]:
        for seed in p["comparison_seeds"]:
            for noise in p["comparison_noise"]:
                case, problem, error, case_hash = build_case(family, seed, noise, noise, "comparison", directory)
                prepared = None if error else prepare_case(case["input"], case["chosenDecision"], case["truth"])
                for planned in (r for r in frozen["comparisonSchedule"] if r["caseId"] == case["id"]):
                    record = {**planned, "caseSha256": case_hash, "executionStatus": "failed"}
                    try:
                        if error:
                            raise RuntimeError(error)
                        result = run_method_v2(problem, planned["method"], planned["budget"], p["method_seconds"])
                        record["result"] = normalize_result(result, case)
                        record["verification"] = verify_prepared(prepared, record["result"])
                        record["executionStatus"] = "complete"
                    except Exception as exc:
                        failures += 1
                        record["error"] = repr(exc)
                    save(directory / "runs" / f"{case['id']}__{planned['method']}__b{planned['budget']}.json", record)
                count += 1
                if count % 5 == 0:
                    print(json.dumps({"phase": "comparison", "completedCases": count, "failedRuns": failures}), flush=True)
    return failures


def endpoint_record(analysis):
    return {**analysis["decisionCertificate"], "witnesses": analysis.get("witnesses", [])}


def check_profile(case, result, cap):
    nominal = endpoint_record(result)
    upper = endpoint_record(result["noiseSensitivity"]["upperAnalysis"])
    up_input = copy.deepcopy(case["input"])
    up_input["certification"]["noise"] = {"kind": "absolute", "budget": cap}
    return {
        "nominal": verify_prepared(prepare_case(case["input"], case["chosenDecision"], case["truth"]), nominal),
        "upper": verify_prepared(prepare_case(up_input, case["chosenDecision"], case["truth"]), upper),
    }


def profile(case, cap, protocol):
    data = copy.deepcopy(case["input"])
    data["certification"].update(
        maxSeconds=protocol["sensitivity_endpoint_seconds"],
        maxOracleCalls=protocol["sensitivity_endpoint_oracle_calls"],
        sensitivity={"upperNoise": {"kind": "absolute", "budget": cap},
                     "maxSeconds": protocol["sensitivity_endpoint_seconds"],
                     "maxOracleCalls": protocol["sensitivity_endpoint_oracle_calls"]})
    result = analyze_with_sensitivity(data, case["pointFit"]["theta"])
    if result["decisionCertificate"]["chosenDecision"] != case["chosenDecision"]:
        raise RuntimeError("Fixed decision changed during sensitivity analysis")
    return result, check_profile(case, result, cap)


def sensitivity(out, frozen):
    p = frozen["protocol"]
    directory = out / "sensitivity"
    count, failures = 0, 0
    for family in p["families"]:
        for seed in p["sensitivity_seeds"]:
            case, _, error, case_hash = build_case(
                family, seed, p["sensitivity_actual_noise"], p["sensitivity_nominal_noise"], "sensitivity", directory)
            for planned in (r for r in frozen["sensitivitySchedule"] if r["caseId"] == case["id"]):
                record = {**planned, "caseSha256": case_hash, "executionStatus": "failed"}
                try:
                    if error:
                        raise RuntimeError(error)
                    record["result"], record["verification"] = profile(case, planned["cap"], p)
                    record["executionStatus"] = "complete"
                except Exception as exc:
                    failures += 1
                    record["error"] = repr(exc)
                save(directory / "profiles" / f"{case['id']}__cap{planned['cap']}.json", record)
            count += 1
            if count % 3 == 0:
                print(json.dumps({"phase": "sensitivity", "completedCases": count, "failedProfiles": failures}), flush=True)
    return failures


def regression(out, frozen):
    paths = list((ROOT / "outputs/comparison-20261020/cases").glob("misspecification-assignment3-s20011-*.json"))
    if len(paths) != 1:
        raise RuntimeError("Prior failure case not uniquely located")
    destination = out / "regression/prior-false-safe.json"
    if destination.exists():
        raise RuntimeError("Refusing to overwrite regression")
    case = json.loads(paths[0].read_text("utf-8"))
    result, audit = profile(case, 1, frozen["protocol"])
    save(destination, {"sourcePath": str(paths[0]), "sourceSha256": sha(paths[0]),
                       "countsAsNewIndependentEvidence": False, "case": case,
                       "cap": 1, "result": result, "verification": audit})
    print(json.dumps({"phase": "regression", "nominal": result["decisionCertificate"]["status"],
                      "sensitivity": result["noiseSensitivity"]["status"]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("comparison", "sensitivity", "regression", "all"), required=True)
    parser.add_argument("--out", default="outputs/followup-20261020")
    args = parser.parse_args()
    out = ROOT / args.out
    p = json.loads((ROOT / "research/followup_protocol.json").read_text("utf-8"))
    frozen = freeze(out, p)
    failures = 0
    if args.phase in ("comparison", "all"):
        failures += comparison(out, frozen)
    if args.phase in ("sensitivity", "all"):
        failures += sensitivity(out, frozen)
    if args.phase in ("regression", "all"):
        regression(out, frozen)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
