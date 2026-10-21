"""Evaluate one saved language proposal; this module never contacts a model."""
import copy
import json
import sys
from fractions import Fraction as Q
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solver"))
from inverse import canonical, forward, recover


def feature_value(feature, action):
    value = sum((Q(str(v)) * action[k] for k, v in feature["terms"].items()), Q(0))
    if feature.get("kind", "linear") == "soft":
        gap = value - Q(str(feature["rhs"]))
        value = max(Q(0), gap if feature["sense"] == "<=" else -gap)
    return value


def evaluate(payload):
    data = copy.deepcopy(payload["proposedInput"])
    task = payload["task"]
    # Deployment has the same physical actions and meanings as both histories.
    # Transfer only the returned model's common feature definition, never truth.
    if any(s["features"] != data["samples"][0]["features"] for s in data["samples"]):
        raise ValueError("Context-invariant task received inconsistent features; no repair allowed")
    fitted = recover(data)
    if fitted["status"] != "optimal":
        raise ValueError("Historical fit failed: " + fitted["status"])
    deployment = copy.deepcopy(task["deployment"])
    deployment["features"] = copy.deepcopy(data["samples"][0]["features"])
    candidate, predicted_cost = forward(canonical(deployment, data["hypotheses"]), fitted["theta"], 5)
    names = [v["name"] for v in deployment["model"]["variables"]]
    chosen = {n: int(round(candidate[n])) for n in names}
    actions = task["feasibleActions"]
    if chosen not in actions or any(abs(candidate[n] - chosen[n]) > 1e-7 for n in names):
        raise ValueError("Solver candidate is not a feasible original action")
    # Independent two-action enumeration validates the forward solver result.
    def predicted(action):
        base = sum((Q(str(v)) * action[n] for n, v in deployment["model"]["objective"].items()), Q(0))
        return base + sum((Q(str(fitted["theta"][h])) * feature_value(f, action)
                           for h, f in deployment["features"].items()), Q(0))
    predicted_values = [predicted(a) for a in actions]
    if predicted(chosen) - min(predicted_values) > Q("0.000001"):
        raise ValueError("Forward solution disagrees with independent enumeration")

    truth = task["hiddenTruth"]
    def true_cost(sample, action):
        base = sum((Q(str(v)) * action[n] for n, v in sample["model"]["objective"].items()), Q(0))
        return base + Q(str(truth["handoverWeight"])) * action["handover"]
    historical_regrets = [
        true_cost(s, s["decision"]) - min(true_cost(s, a) for a in actions)
        for s in data["samples"]
    ]
    costs = [true_cost(deployment, a) for a in actions]
    regret = true_cost(deployment, chosen) - min(costs)
    threshold = Q(str(task["dangerThreshold"]))
    dangerous = regret > threshold
    declared = Q(str(task["declaredNoiseCap"]))
    actual = Q(str(task["actualNoiseCap"]))
    if not declared < max(historical_regrets) <= actual:
        raise ValueError("This instance does not realize the declared misspecification")
    # The primary starting arm is language structure + inverse fit, without audit.
    # Release is the predeclared behavior of this arm, not a safety certificate.
    released = True
    metrics = {
        "plannedInstances": 1, "completedInstances": 1,
        "dangerousPlans": int(dangerous), "releasedPlans": int(released),
        "dangerousReleasedPlans": int(dangerous and released),
        "dangerousPlanReleaseRate": float(released) if dangerous else None,
        "dangerousReleaseFractionOfAllInstances": int(dangerous and released),
        "postAuditDangerousPlanReleaseRate": None,
        "preAuditUsablePlanAvailabilityRate": None,
        "postAuditUsablePlanAvailabilityRate": None,
    }
    science = {
        "arm": "language_structure_plus_inverse_fit",
        "releaseRule": "Release a feasible optimal point-estimate recommendation; no risk audit.",
        "selectedDecision": chosen, "fittedTheta": fitted["theta"],
        "meanTrainingResidual": fitted["meanResidual"],
        "predictedDeploymentCosts": [str(v) for v in predicted_values],
        "trueDeploymentCosts": [str(v) for v in costs],
        "trueRegret": str(regret), "dangerThreshold": str(threshold),
        "historicalTrueRegrets": [str(v) for v in historical_regrets],
        "declaredNoiseCap": str(declared), "actualNoiseCap": str(actual),
        "dangerous": dangerous, "released": released, "metrics": metrics,
        "scope": "One deliberately constructed synthetic counterexample, not a population rate.",
    }
    return {"status": "complete", "science": science, "fit": fitted,
            "deploymentWithModelFeatures": deployment,
            "forwardPredictedCost": predicted_cost}


if __name__ == "__main__":
    try:
        print(json.dumps(evaluate(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
