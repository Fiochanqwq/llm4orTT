"""Prospectively fixed small finite cases and truth-free method input adapter."""
import itertools
import random
import sys
import time
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solver"))
from inverse import recover


def rat(value):
    return F(str(value))


def actions_for(family, names, capacity_weights=None):
    if family == "menu8":
        return [{n: int(i == j) for j, n in enumerate(names)} for i in reversed(range(len(names)))]
    if family == "assignment3":
        return [{f"x{i}{j}": int(j == permutation[i]) for i in range(3) for j in range(3)}
                for permutation in reversed(list(itertools.permutations(range(3))))]
    return [dict(zip(names, values)) for values in itertools.product((0, 1), repeat=len(names))
            if sum(capacity_weights[n] * v for n, v in zip(names, values)) <= 9]


def make_case(family, seed, actual_noise, declared_noise, split):
    # Generator is fixed before comparison. Conditions share base coefficients,
    # but feedback random streams never alter the contexts.
    family_code = {"menu8": 11, "knapsack7": 23, "assignment3": 37}[family]
    rng = random.Random(seed * 101 + family_code)
    feedback = random.Random(seed * 103 + family_code)
    truth = {"p0": rng.randint(2, 18) / 10, "p1": rng.randint(2, 18) / 10}
    hypotheses = [{"id": f"p{j}", "label": f"cost-{j}", "lower": 0, "upper": 2} for j in range(2)]
    samples, tables = [], []
    for context in range(9):
        names = [f"x{i}{j}" for i in range(3) for j in range(3)] if family == "assignment3" else [
            f"x{j}" for j in range(8 if family == "menu8" else 7)]
        base = {n: rng.randint(-30, 30) / 10 for n in names}
        if not any(base.values()):
            base[names[0]] = 1
        features = {h["id"]: {"kind": "linear", "terms": {n: rng.randint(-4, 5) for n in names}} for h in hypotheses}
        weights = {n: rng.randint(1, 6) for n in names}
        if family == "menu8":
            constraints = [{"terms": {n: 1 for n in names}, "sense": "=", "rhs": 1}]
        elif family == "assignment3":
            constraints = [{"terms": {f"x{i}{j}": 1 for j in range(3)}, "sense": "=", "rhs": 1} for i in range(3)]
            constraints += [{"terms": {f"x{i}{j}": 1 for i in range(3)}, "sense": "=", "rhs": 1} for j in range(3)]
        else:
            constraints = [{"terms": weights, "sense": "<=", "rhs": 9}]
        actions = actions_for(family, names, weights)
        actions.sort(key=lambda a: tuple(a[n] for n in names))
        table = []
        for action in actions:
            b = sum((rat(base[n]) * v for n, v in action.items()), F(0))
            f = tuple(sum((rat(features[h["id"]]["terms"][n]) * v for n, v in action.items()), F(0))
                      for h in hypotheses)
            table.append({"decision": action, "base": b, "features": f})
        costs = [a["base"] + sum(f * rat(truth[h["id"]]) for f, h in zip(a["features"], hypotheses)) for a in table]
        eligible = [j for j, c in enumerate(costs) if c - min(costs) <= rat(actual_noise)]
        chosen = feedback.choice(eligible) if context < 8 else 0
        samples.append({"id": f"context-{context}", "model": {"sense": "minimize",
            "variables": [{"name": n, "type": "binary", "lower": 0, "upper": 1} for n in names],
            "objective": base, "constraints": constraints}, "features": features,
            "decision": table[chosen]["decision"]})
        tables.append(table)
    data = {"schema": "contextual-inverse.v1", "hypotheses": hypotheses, "samples": samples[:8],
            "deployment": samples[8], "lambda": 0, "pruneThreshold": 0, "maxIterations": 100,
            "seconds": 5, "certification": {"noise": {"kind": "absolute", "budget": declared_noise},
                                         "threshold": .25}}
    return {"input": data, "truth": truth, "metadata": {"family": family, "seed": seed, "split": split,
            "actualNoise": actual_noise, "declaredNoise": declared_noise,
            "independentInstance": f"{family}-s{seed}", "synthetic": True,
            "deploymentDecision": "truth-independent feasible placeholder"}}, tables


def prepare_problem(case, tables):
    started = time.monotonic()
    data = case["input"]
    fit = recover(data)
    if fit["status"] != "optimal":
        raise RuntimeError("Shared old point fit not optimal: " + fit["status"])
    ids = [h["id"] for h in data["hypotheses"]]
    theta = [rat(fit["theta"][i]) for i in ids]
    chosen = min(tables[-1], key=lambda a: a["base"] + sum(f * t for f, t in zip(a["features"], theta)))
    case["chosenDecision"] = chosen["decision"]
    case["pointFit"] = {"theta": fit["theta"], "status": fit["status"], "lambda": 0}
    problem = problem_from_case(case, tables)
    case["preprocessing"] = {"elapsedMs": (time.monotonic() - started) * 1000,
                            "historyActionCounts": [len(t) for t in tables[:8]],
                            "deploymentActionCount": len(tables[-1]),
                            "historyRows": sum(map(len, problem["histories"]))}
    return problem


def problem_from_case(case, tables):
    """Rebuild truth-free method input without refitting a persisted decision."""
    data = case["input"]
    ids = [h["id"] for h in data["hypotheses"]]
    chosen = next(a for a in tables[-1] if a["decision"] == case["chosenDecision"])
    histories = []
    for s, table in zip(data["samples"], tables):
        observation = next(a for a in table if a["decision"] == s["decision"])
        delta = rat(data["certification"]["noise"]["budget"])
        histories.append([(tuple(f - g for f, g in zip(observation["features"], a["features"])),
                           delta - observation["base"] + a["base"]) for a in table])
    rivals = [(chosen["base"] - a["base"],
               tuple(f - g for f, g in zip(chosen["features"], a["features"]))) for a in tables[-1]]
    return {"box": [(rat(h["lower"]), rat(h["upper"])) for h in data["hypotheses"]],
            "histories": histories, "rivals": rivals,
            "threshold": rat(data["certification"]["threshold"]),
            "parameterIds": ids, "chosenDecision": chosen["decision"]}
