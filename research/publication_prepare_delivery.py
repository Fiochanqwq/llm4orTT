"""Collect engineering and historical evidence before writing report claims."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text("utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    events = [json.loads(line) for line in (out / "lifecycle.jsonl").read_text("utf-8").splitlines() if line]
    passed = {event["phase"]: event for event in events if event["exitCode"] == 0}
    required = ("certification-tests", "application-tests", "typescript", "frontend-build")
    if any(stage not in passed for stage in required):
        raise ValueError("Missing successful lifecycle evidence")
    if "scientific-study" not in passed:
        if ("scientific-audit-repair" not in passed or not read(out / "archive-amendment.json")["originalFreezeRetained"]
                or not read(out / "independent-followup-audit.json")["allPassed"]):
            raise ValueError("Scientific study has not passed an original or explicitly amended audit")
    pytext = (out / passed["certification-tests"]["log"]).read_text("utf-8")
    nodetext = (out / passed["application-tests"]["log"]).read_text("utf-8")
    python_tests = int(re.search(r"Ran (\d+) tests", pytext)[1])
    node_tests = int(re.search(r"tests (\d+)", nodetext)[1])
    if not re.search(r"\bOK\b", pytext) or not re.search(r"fail 0\b", nodetext):
        raise ValueError("Test logs do not show a passing result")
    api = read(out / "api-verification.json")
    if api["passed"] is not True:
        raise ValueError("API verification failed")
    names = ("inverse.py", "inverse_local.py", "inverse_benchmark.py", "inverse_certified.py", "inverse_sensitivity.py")
    parity = [{"file": name, "sourceSha256": sha(ROOT / "solver" / name),
               "releaseMatches": (ROOT / "resources/solver" / name).exists()
               and (ROOT / "solver" / name).read_bytes() == (ROOT / "resources/solver" / name).read_bytes()}
              for name in names]
    historical = ROOT / "实验/逆优化实验_2026-10-20_DeepSeek文本闭环"
    command = [sys.executable, "-X", "utf8", str(ROOT / "research/verify_llm_grounding_bundle.py"), str(historical)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    historical_result = json.loads(result.stdout)
    historical_result.update(sourceDirectory=str(historical), verifiedDate="2026-10-21",
                             verifierSha256=sha(ROOT / "research/verify_llm_grounding_bundle.py"),
                             manifestSha256=sha(historical / "CHECKSUMS.json"),
                             countsAsNewExperimentalEvidence=False)
    (out / "historical-language-audit.json").write_text(
        json.dumps(historical_result, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"pythonTests": python_tests, "nodeTests": node_tests, "passingStages": passed,
              "apiPassed": api["passed"], "productionSolverParity": parity,
              "productionSolverCopiesMatch": all(row["releaseMatches"] for row in parity)}
    (out / "engineering-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"pythonTests": python_tests, "nodeTests": node_tests,
                      "productionSolverCopiesMatch": report["productionSolverCopiesMatch"],
                      "historicalEvidenceChecks": historical_result["arithmeticAndEvidenceChecks"]}))


if __name__ == "__main__":
    main()
