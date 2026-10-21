"""Standalone standard-library integrity check; does not execute bundled code."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def verify(root, archive=None):
    root = Path(root).resolve()
    manifest = json.loads((root / "CHECKSUMS.json").read_text("utf-8"))
    if not manifest.get("files"):
        raise ValueError("Empty evidence manifest")
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Unsafe manifest path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Evidence hash mismatch: " + name)
    if archive:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive entry")
            for name, expected in manifest["files"].items():
                if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                    raise ValueError("Archive hash mismatch: " + name)
            if bundle.read("CHECKSUMS.json") != (root / "CHECKSUMS.json").read_bytes():
                raise ValueError("Archive manifest differs")
    return {"passed": True, "verifiedFiles": len(manifest["files"]),
            "archiveVerified": archive is not None, "scope": "File integrity; scientific validity is in the independent audit."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.archive)))
