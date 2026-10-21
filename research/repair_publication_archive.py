"""Create a disclosed archive-only revision; preserve every scientific outcome."""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from experiment_runtime import read, save, sha, seal_record, utc_now
from publication_pipeline import archive_regression_case
from verify_followup import audit_followup
from analyze_followup import analyze_directory

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    archive_root = (ROOT / "实验").resolve()
    if not source.is_relative_to(archive_root) or not out.is_relative_to(archive_root) or out == source:
        raise ValueError("Use two distinct directories inside the experiment archive")
    old = read(source / "independent-followup-audit.json")
    if (old["regression"].get("error") != "Case payload identifier differs from filename"
            or not all(old[k]["allPassed"] for k in ("comparison", "sensitivity", "frozenSources", "completeness"))):
        raise ValueError("This repair applies only to the documented regression filename error")
    if out.exists():
        raise FileExistsError("An archive revision must use a new directory")
    tick = time.monotonic()
    def ignored(directory, names):
        skipped = {".run.lock", "CHECKSUMS.json", "证据包.zip"}
        if Path(directory) == source / "regression":
            skipped |= {"prior-false-safe.json", "prior-false-safe.json.sha256"}
        return [n for n in names if n in skipped]
    shutil.copytree(source, out, ignore=ignored)
    (out / "audit-history").mkdir()
    for name in ("independent-followup-audit.json", "analysis.json", "study-status.json"):
        shutil.copy2(source / name, out / "audit-history" / ("v1-" + name))
    original = read(source / "regression/prior-false-safe.json")
    original_case = Path(original["originalSource"])
    local = archive_regression_case(out, original_case)
    corrected = {**original, "sourcePath": str(local), "sourceSha256": sha(local)}
    assert corrected["case"] == original["case"] and corrected["result"] == original["result"]
    seal_record(out / "regression/prior-false-safe.json", corrected)
    baseline = read(source / "resume-baseline.json")
    changed = [name for name, digest in baseline.items() if sha(out / name) != digest]
    if changed:
        raise ValueError("Scientific records changed during archive copy")
    amendment = {
        "schema": "publication-archive-amendment.v1", "createdUTC": utc_now(),
        "originalDirectory": str(source), "originalAuditSha256": sha(source / "independent-followup-audit.json"),
        "repairCodeSha256": sha(Path(__file__)),
        "type": "post-execution archival association repair; not a new experiment",
        "reason": "Regression source basename must equal the original case identifier",
        "changedFields": ["regression/prior-false-safe.json: sourcePath, sourceSha256"],
        "unchangedScientificFiles": len(baseline), "newScientificRuns": 0,
        "originalFreezeRetained": True, "originalFailedAuditRetained": True,
        "regressionResultUnchanged": True, "sourceCodeFix": "publication_pipeline.archive_regression_case",
        "interpretation": "Original prospective freeze describes actual execution. The current runner fixes copying for future batches; it is not relabeled as the original execution source.",
    }
    seal_record(out / "archive-amendment.json", amendment)
    report = audit_followup(out)
    save(out / "independent-followup-audit.json", report)
    analysis = analyze_directory(out)
    success = report["allPassed"] and analysis["comparisonComplete"] and analysis["sensitivityComplete"]
    save(out / "study-status.json", {
        "schema": "publication-study-status.v1", "finishedUTC": utc_now(), "complete": success,
        "promotionGateMet": analysis["primary"]["candidatePromotionGateMet"],
        "publicationReady": False, "newModelCalls": 0, "archiveRevision": True,
        "reason": "Scientific records unchanged; regression source association repaired and independently re-audited.",
    })
    log = out / "logs/archive-revision-audit.log"
    save(log, {"allPassed": success, "unchangedScientificFiles": len(baseline),
               "comparisonRuns": report["comparison"]["runs"], "sensitivityProfiles": report["sensitivity"]["profiles"]})
    with (out / "lifecycle.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"phase": "scientific-audit-repair", "exitCode": 0 if success else 1,
                                "wallSeconds": time.monotonic()-tick, "finishedUTC": utc_now(),
                                "log": log.relative_to(out).as_posix(), "newScientificRuns": 0}) + "\n")
    print(json.dumps({"archiveRevisionPassed": success, "unchangedScientificFiles": len(baseline),
                      "newScientificRuns": 0, "output": str(out)}, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
