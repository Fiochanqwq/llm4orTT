"""Shared, fail-closed experiment storage and provenance primitives."""
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    """Atomically publish complete JSON; serialization failure preserves old bytes."""
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def runtime():
    return {
        "python": sys.version, "platform": platform.platform(),
        "executable": sys.executable, "logicalCpus": os.cpu_count(),
        "processor": platform.processor(),
        **{name: importlib.metadata.version(name) for name in ("highspy", "numpy", "pyomo")},
    }


@contextmanager
def exclusive_run(directory):
    """OS-owned advisory lock: concurrent writers fail; process exit releases it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / ".run.lock").open("a+b")
    stream.seek(0, os.SEEK_END)
    if not stream.tell():
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def seal_record(path, value):
    """Create an immutable outcome and its digest; never retry a recorded failure."""
    path = Path(path)
    digest = path.with_suffix(path.suffix + ".sha256")
    if path.exists() or digest.exists():
        raise FileExistsError(f"Refusing to replace recorded evidence: {path}")
    save(path, value)
    # A crash between these two writes deliberately blocks automatic reuse.
    save(digest, {"sha256": sha(path)})


def load_record(path):
    path = Path(path)
    expected = read(path.with_suffix(path.suffix + ".sha256"))["sha256"]
    if sha(path) != expected:
        raise ValueError(f"Evidence digest mismatch: {path}")
    return read(path)


def freeze_sources(root, out, protocol_path, protocol, sources, schedules, resume=False):
    root, out = Path(root), Path(out)
    protocol_name = Path(protocol_path).resolve().relative_to(root.resolve()).as_posix()
    sources = sorted(set(sources) | {protocol_name})
    hashes = {name: sha(root / name) for name in sources}
    path = out / "freeze.json"
    if path.exists():
        if not resume:
            raise FileExistsError("Study already exists. Use --resume to retain recorded outcomes.")
        frozen = load_record(path)
        if frozen["protocol"] != protocol or frozen["sourceHashes"] != hashes:
            raise ValueError("Protocol/source drift: retain this study and create a new version.")
        if frozen["runtime"] != runtime():
            raise ValueError("Runtime drift: resume requires the frozen software environment.")
        for name, digest in hashes.items():
            if sha(out / "frozen-source" / name) != digest:
                raise ValueError("Frozen snapshot changed: " + name)
        for key, schedule in schedules.items():
            if frozen[key] != schedule:
                raise ValueError("Schedule drift: " + key)
        return frozen
    if resume:
        raise FileNotFoundError("Cannot resume without an intact freeze record.")
    for name in sources:
        destination = out / "frozen-source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((root / name).read_bytes())
    frozen = {
        "schema": "publication-study-freeze.v1", "createdUTC": utc_now(),
        "localProspectiveFreeze": True, "publicRegistryRegistration": False,
        "protocolPath": protocol_name, "protocol": protocol,
        "sourceHashes": hashes, "runtime": runtime(), **schedules,
    }
    seal_record(path, frozen)
    return frozen
