"""Prespecified high-density stress generator; no response-based selection."""
import random
from fractions import Fraction as Q

from language_instances import DOMAINS, generate

SEEDS = list(range(82001, 82021))
ORDER_SEED = 82000001
TRUTH_OFFSET_TENTHS = 8
NEAR_BOUNDARY_PER_DOMAIN = 12


def inventory():
    result = [{"domain": d, "seed": s} for d in DOMAINS for s in SEEDS]
    random.Random(ORDER_SEED).shuffle(result)
    return result


def near_boundary_seeds(domain):
    code = {"dispatch": 13, "staffing": 29, "workshop": 47}[domain]
    return set(random.Random(82010001 + code).sample(SEEDS, NEAR_BOUNDARY_PER_DOMAIN))


def materialize_density(domain, seed):
    blueprint = generate(domain, seed)
    design = blueprint["design"]
    ids = design["factorIds"]
    active = ids[design["phenomenonIndex"]]
    rng = random.Random(seed * 1009 + design["domainCode"])
    true_weight = rng.randint(12, 18)
    reference = {h: true_weight - TRUTH_OFFSET_TENTHS if h == active else 0 for h in ids}
    truth = {h: true_weight if h == active else 0 for h in ids}
    histories = []
    # Two decisions at each reference indifference point give six histories.
    # Their true regret is either 0 or 0.8, so every history remains inside cap 1.
    for j, h in enumerate(ids):
        actions = [
            {"id": "p0", "knownCostTenths": 10, "monitors": {k: int(k == h) for k in ids}},
            {"id": "p1", "knownCostTenths": 10 + reference[h], "monitors": {k: 0 for k in ids}},
            {"id": "p2", "knownCostTenths": 30, "monitors": {k: int(k == h) for k in ids}},
            {"id": "p3", "knownCostTenths": 30 + reference[h], "monitors": {k: 0 for k in ids}},
        ]
        for choice in (0, 1):
            histories.append({"id": f"context-{j}-{choice}", "actions": actions, "chosen": f"p{choice}"})
    rng.shuffle(histories)
    near = seed in near_boundary_seeds(domain)
    margin = rng.choice((3, 4))
    quote = true_weight - margin if near else reference[active] - 2
    actions = []
    for index, (count, cost) in enumerate(((1, 10), (0, 10 + quote), (1, 30), (0, 30 + quote))):
        monitors = {h: rng.randint(0, 3) for h in ids}
        monitors[active] = count
        actions.append({"id": f"p{index}", "knownCostTenths": cost, "monitors": monitors})
    public = {**blueprint["public"], "histories": histories,
              "deployment": {"id": "deployment", "actions": actions}}
    regrets = []
    for context in histories:
        costs = {a["id"]: a["knownCostTenths"] + sum(a["monitors"][h] * w for h, w in truth.items())
                 for a in context["actions"]}
        regrets.append(Q(costs[context["chosen"]] - min(costs.values()), 10))
    if max(regrets) > 1:
        raise ValueError("Generator exceeds the true history-noise cap")
    private = {
        "thetaTenths": truth, "activeFactor": active, "distractors": [h for h in ids if h != active],
        "behaviorNoiseCap": 1, "declaredNoiseCap": 0, "dangerThreshold": "1/4",
        "realizedHistoryRegrets": [str(v) for v in regrets], "realizedMisspecification": True,
        "generator": {"profile": "density-v1", "nearBoundary": near,
                      "referenceThetaTenths": reference, "truthOffsetTenths": TRUTH_OFFSET_TENTHS,
                      "nearBoundaryMarginTenths": margin if near else None},
    }
    return blueprint, public, private
