"""Actual language call accounting, independent of offline API assertions."""
import json
from pathlib import Path


def count_language_calls(out):
    stage = Path(out) / "language"
    if not stage.exists():
        return {"newModelCalls": 0, "formalCalls": 0, "pilotCalls": 0,
                "responsesReceived": 0, "completedCalls": 0, "inputTokens": 0, "outputTokens": 0,
                "callsWithoutUsage": 0}
    read = lambda p: json.loads(p.read_text("utf-8"))
    frozen = read(stage / "freeze.json")
    result = {"newModelCalls": 0, "formalCalls": 0, "pilotCalls": 0,
              "responsesReceived": 0, "completedCalls": 0, "inputTokens": 0, "outputTokens": 0,
              "callsWithoutUsage": 0}
    expected = {stage / e["relativeDirectory"] for e in frozen["entries"]}
    actual = {p.parent for p in stage.rglob("call.started.json")}
    if not actual <= expected:
        raise ValueError("Unplanned language calls found")
    for entry in frozen["entries"]:
        folder = stage / entry["relativeDirectory"]
        if not (folder / "call.started.json").exists():
            if (folder / "call.json").exists() and read(folder / "call.json").get("newModelCalls", 0):
                raise ValueError("Call without its start record")
            continue
        start = read(folder / "call.started.json")
        if start["newModelCalls"] != 1 or start["retries"] != 0:
            raise ValueError("Invalid call count/retry declaration")
        result["newModelCalls"] += 1
        result["formalCalls" if entry["phase"] == "instances" else "pilotCalls"] += 1
        final = read(folder / "call.json") if (folder / "call.json").exists() else {}
        if final.get("newModelCalls", 1) != 1:
            raise ValueError("Final call count changed")
        result["responsesReceived"] += final.get("responsesReceived", 0)
        result["completedCalls"] += final.get("callStatus") == "complete"
        usage = (final.get("inputTokens"), final.get("outputTokens"))
        if all(type(v) is int for v in usage):
            result["inputTokens"] += usage[0]
            result["outputTokens"] += usage[1]
        else:
            result["callsWithoutUsage"] += 1
    if result["newModelCalls"] > frozen["budget"]["maxModelCalls"]:
        raise ValueError("Model-call budget exceeded")
    return result
