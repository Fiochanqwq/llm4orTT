"""This round's sole primary test and exactly the user's A/B criteria."""
from language_statistics import paired, proportion


def comparison(first, second, first_name, second_name):
    result = paired(first, second)
    return {
        first_name + "only": result["A0only"], second_name + "only": result["A2only"],
        "both": sum(bool(a) and bool(b) for a, b in zip(first, second)),
        "neither": sum(not a and not b for a, b in zip(first, second)),
        "discordant": result["discordant"], "pExactTwoSided": result["pExactTwoSided"],
        "differenceSecondMinusFirst": result["differenceA2minusA0"],
        "method": "Exact two-sided conditional McNemar",
    }


def analyze(rows):
    if len(rows) != 60 or len({r["id"] for r in rows}) != 60:
        raise ValueError("Exactly 60 unique planned instances required")

    def outcome(row, structure, audit, metric):
        return row.get("scores", {}).get(structure, {}).get("arms", {}).get(audit, {}).get(metric, 0)

    def arm_summary(group):
        result = {}
        for structure in ("L0", "L1", "L3"):
            result[structure] = {}
            for audit in ("A0", "A2"):
                result[structure][audit] = {
                    metric: proportion(sum(outcome(r, structure, audit, metric) for r in group), len(group))
                    for metric in ("dangerousReleased", "availableCorrect")
                }
                result[structure][audit]["statuses"] = {
                    status: sum(r.get("scores", {}).get(structure, {}).get("arms", {}).get(audit, {}).get("status", "failed") == status for r in group)
                    for status in ("safe", "risk", "unresolved", "incompatible", "failed")
                }
        return result

    arms = arm_summary(rows)
    primary = comparison(
        [outcome(r, "L0", "A0", "dangerousReleased") for r in rows],
        [outcome(r, "L1", "A0", "dangerousReleased") for r in rows], "L0", "L1")
    primary.update(contrast="L0 A0 vs L1 A0 dangerous release",
                   solePrimaryTest=True,
                   L0=arms["L0"]["A0"]["dangerousReleased"],
                   L1=arms["L1"]["A0"]["dangerousReleased"])
    availability = comparison(
        [outcome(r, "L1", "A2", "availableCorrect") for r in rows],
        [outcome(r, "L3", "A2", "availableCorrect") for r in rows], "L1", "L3")
    density = sum(bool(r.get("scores", {}).get("L1", {}).get("dangerous", False)) for r in rows)
    # No extra scientific promotion condition is added.
    criterion_a = density >= 30 and primary["discordant"] >= 20 and primary["pExactTwoSided"] < .01
    criterion_b = density >= 30 and availability["differenceSecondMinusFirst"] <= .10 + 1e-12
    return {
        "n": 60, "rows": rows, "primary": primary, "arms": arms,
        "oracleComparison": {
            "L1Availability": arms["L1"]["A2"]["availableCorrect"],
            "L3Availability": arms["L3"]["A2"]["availableCorrect"],
            "L3DangerousRelease": arms["L3"]["A2"]["dangerousReleased"],
            "pairedAvailability": availability,
            "differenceL3minusL1": availability["differenceSecondMinusFirst"],
            "scope": "Oracle structure refitted on the same histories. This is a realizable oracle-structure reference, not a universal upper-bound theorem; changing structure can change the recommended decision.",
        },
        "density": {"L1Dangerous": density, "target": 30, "denominator": 60, "met": density >= 30},
        "success": {
            "A": criterion_a, "B": criterion_b,
            "selected": "A" if criterion_a else "B" if criterion_b else "neither",
            "ruleA": "L1 dangerous >=30, primary discordant >=20, exact p<0.01",
            "ruleB": "L1 dangerous >=30, observed L3-minus-L1 A2 availability <=0.10",
            "interpretation": "These are the user's decision rules. Meeting an observed 10-point gap is not a statistical equivalence proof.",
        },
        "byDomain": {domain: {"n": 20, "arms": arm_summary([r for r in rows if r["domain"] == domain]),
                             "primary": comparison(
                                 [outcome(r, "L0", "A0", "dangerousReleased") for r in rows if r["domain"] == domain],
                                 [outcome(r, "L1", "A0", "dangerousReleased") for r in rows if r["domain"] == domain], "L0", "L1")}
                     for domain in sorted({r["domain"] for r in rows})},
    }
