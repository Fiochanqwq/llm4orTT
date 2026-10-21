"""Seal deliverables after visual QA; preserve raw results and their source."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_publication_bundle import verify

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to((ROOT / "实验").resolve()):
        raise ValueError("Evidence must stay in the project archive")
    if not json.loads((out / "report-qa.json").read_text("utf-8"))["passed"]:
        raise ValueError("Report QA has not passed")
    for name in ("publication_report.py", "publication_prepare_delivery.py", "publication_pdf_qa.py", "publication_pipeline.py", "verify_followup.py", "repair_publication_archive.py", "verify_publication_bundle.py", "seal_publication.py",
                 "REPRODUCE_PUBLICATION.txt"):
        destination = out / "delivery-source/research" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "research" / name, destination)
    for name in ("publication-deliver.mjs", "publication-report-qa.mjs"):
        destination = out / "delivery-source/scripts" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / name, destination)
    test_copy = out / "delivery-source/tests/test_experiment_runtime.py"
    test_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tests/test_experiment_runtime.py", test_copy)
    shutil.copy2(ROOT / "research/verify_publication_bundle.py", out / "verify_bundle.py")
    excluded = {"CHECKSUMS.json", "证据包.zip", "bundle-verification.json", ".run.lock"}
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob("*")) if p.is_file() and p.name not in excluded
             and "__pycache__" not in p.parts}
    manifest = {"schema": "publication-delivery-manifest.v1", "files": files,
                "excludedGeneratedFiles": sorted(excluded),
                "scope": "Local reproducibility archive; no external publication or upload."}
    (out / "CHECKSUMS.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    archive = out / "证据包.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name in files:
            bundle.write(out / name, name)
        bundle.write(out / "CHECKSUMS.json", "CHECKSUMS.json")
    report = verify(out, archive)
    report["archiveSha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / "bundle-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
