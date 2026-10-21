"""Research-only, auditable threshold certification comparisons.

The candidate deployment action is fixed before this module is called.  Inputs
contain only the declared parameter box, history inequalities, and deployment
cost differences.  Every method uses identical exact feasibility checks and
global witness reuse.  This module makes no claim of algorithmic novelty.

For rival j, its affine regret is c_j + q_j * theta.  Regret is the maximum of
zero and all rival regrets over the jointly compatible parameter set.  The
implicit zero is valid because the fixed candidate itself is a feasible action.
"""
import math
import sys
import time
from fractions import Fraction as Q
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solver"))

from inverse_certified import CompatibleSet, outward, scalar


METHODS = (
    "full_priority",
    "lazy_sequential",
    "lazy_priority",
    "witness_priority",
    "dual_reuse",
)


def _fraction(value):
    if isinstance(value, bool) or not isinstance(value, (int, Q)):
        raise ValueError("Research inputs must use exact Fraction or integer values")
    return Q(value)


def _normalize(problem):
    box = [tuple(_fraction(x) for x in bounds) for bounds in problem["box"]]
    if not box or any(len(bounds) != 2 or bounds[0] > bounds[1] for bounds in box):
        raise ValueError("A nonempty ordered parameter box is required")
    dimension = len(box)
    histories = []
    for history in problem["histories"]:
        normalized = []
        for a, b in history:
            a = tuple(_fraction(x) for x in a)
            if len(a) != dimension:
                raise ValueError("History dimension does not match the parameter box")
            normalized.append((a, _fraction(b)))
        histories.append(normalized)
    rivals = []
    for constant, objective in problem["rivals"]:
        objective = tuple(_fraction(x) for x in objective)
        if len(objective) != dimension:
            raise ValueError("Rival dimension does not match the parameter box")
        rivals.append((_fraction(constant), objective))
    threshold = _fraction(problem["threshold"])
    if threshold < 0:
        raise ValueError("Regret threshold must be nonnegative")
    return box, histories, rivals, threshold


class _AuditSet(CompatibleSet):
    """Record valid dual vectors without changing the installed solver module."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dual_proofs = []

    def dual_upper(self, objective, multipliers):
        original = [max(Q(0), Q(y)) for y in multipliers]
        # Any nonnegative multipliers are valid. Rationalizing is a shared
        # numerical safeguard, not an assumption that the LP dual is exact.
        rationalized = [y.limit_denominator(10**9) for y in original]
        choices = [
            (CompatibleSet.dual_upper(self, objective, y), y)
            for y in (original, rationalized)
        ]
        bound, selected = min(choices, key=lambda item: item[0])
        weighted = [Q(0)] * self.dimension
        offset = Q(0)
        sparse = []
        for index, ((a, b), y) in enumerate(zip(self.rows, selected)):
            if y:
                sparse.append([index, str(y)])
                offset += y * b
                weighted = [v + y * coefficient for v, coefficient in zip(weighted, a)]
        self.dual_proofs.append({
            "rowCount": len(self.rows),
            "multipliers": sparse,
            "weightedRowExact": [str(x) for x in weighted],
            "offsetExact": str(offset),
            "sourceObjective": [str(x) for x in objective],
            "sourceUpperExact": str(bound),
        })
        return bound


def run_method(problem, method, max_lp_calls, max_seconds):
    """Return a JSON-serializable, conservative certificate and an audit trail.

    LP budgets count calls to lp_proposal, not history separation calls.  Time
    limits include normalization and row setup and are cooperative: one exact
    scan/reconstruction/serialization can finish after the deadline.  Every
    uncompleted rival retains a valid box or dual upper bound.  A safe result
    requires a checked compatible witness, including when all box bounds are
    already below the threshold.
    """
    started = time.monotonic()
    if method not in METHODS:
        raise ValueError("Unknown method: " + str(method))
    if isinstance(max_lp_calls, bool) or not isinstance(max_lp_calls, int) or max_lp_calls < 0:
        raise ValueError("max_lp_calls must be a nonnegative integer")
    if (isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds) or max_seconds <= 0):
        raise ValueError("max_seconds must be finite and positive")
    box, histories, rivals, threshold = _normalize(problem)
    engine = _AuditSet(box, histories, max_seconds, max_lp_calls, started)
    upper = [constant + engine.box_support(q) for constant, q in rivals]
    lower = [None] * len(rivals)
    upper_proofs = [{"kind": "box"} for _ in rivals]
    initial_order = sorted(range(len(rivals)), key=lambda j: (-upper[j], j))
    order = list(range(len(rivals))) if method == "lazy_sequential" else initial_order
    full = method == "full_priority"
    adaptive = method in ("witness_priority", "dual_reuse")
    total_rows = sum(map(len, histories))
    solver_seconds = oracle_seconds = bound_seconds = 0.0
    row_evaluations = witness_evaluations = dual_evaluations = 0
    cumulative_lp_rows = 0
    peak_lp_rows = 0
    invoked_lp_calls = 0
    stalled = set()
    trace = []
    stop_reason = "lp_budget"
    setup_complete = True
    if full:
        for history in histories:
            for a, b in history:
                if time.monotonic() >= engine.deadline:
                    setup_complete = False
                    break
                engine.add_row(a, b)
            if not setup_complete:
                break

    def bounds():
        lo = max([Q(0)] + [value for value in lower if value is not None]) if engine.witnesses else None
        hi = max([Q(0)] + upper)
        return lo, hi

    def decision():
        if engine.empty:
            return "incompatible"
        lo, hi = bounds()
        if engine.witnesses and lo > threshold:
            return "risk_witness"
        if engine.witnesses and hi <= threshold:
            return "safe"
        return "unresolved"

    while setup_complete and invoked_lp_calls < max_lp_calls and time.monotonic() < engine.deadline:
        if decision() != "unresolved":
            stop_reason = "threshold_decided"
            break
        unresolved = [j for j in order if upper[j] > threshold and j not in stalled]
        if unresolved:
            selected = max(unresolved, key=lambda j: (upper[j], -j)) if adaptive else unresolved[0]
            objective = rivals[selected][1]
        elif not engine.witnesses:
            selected = None
            objective = tuple(Q(0) for _ in box)
        else:
            stop_reason = "unresolved_numerical_gap"
            break

        rows_before = len(engine.rows)
        old_upper = upper[selected] if selected is not None else None
        proof_start = len(engine.dual_proofs)
        tick = time.monotonic()
        invoked_lp_calls += 1
        theta, proposed_upper, solver_status = engine.lp_proposal(objective)
        solver_seconds += time.monotonic() - tick
        cumulative_lp_rows += rows_before
        peak_lp_rows = max(peak_lp_rows, rows_before)

        tick = time.monotonic()
        new_proofs = list(range(proof_start, len(engine.dual_proofs)))
        if selected is not None:
            candidate = rivals[selected][0] + proposed_upper
            if candidate < upper[selected]:
                upper[selected] = candidate
                matching = [
                    p for p in new_proofs
                    if engine.dual_proofs[p]["sourceObjective"] == [str(x) for x in objective]
                    and Q(engine.dual_proofs[p]["sourceUpperExact"]) == proposed_upper
                ]
                upper_proofs[selected] = (
                    {"kind": "dual", "proofIndex": matching[-1]} if matching else {"kind": "box"}
                )
        if method == "dual_reuse" and not engine.empty:
            for proof_index in new_proofs:
                proof = engine.dual_proofs[proof_index]
                offset = Q(proof["offsetExact"])
                weighted = tuple(Q(x) for x in proof["weightedRowExact"])
                for j, (constant, q) in enumerate(rivals):
                    candidate = constant + offset + engine.box_support(
                        tuple(a - b for a, b in zip(q, weighted)))
                    dual_evaluations += 1
                    if candidate < upper[j]:
                        upper[j] = candidate
                        upper_proofs[j] = {"kind": "dual", "proofIndex": proof_index}
        bound_seconds += time.monotonic() - tick
        member = None
        new_witness = False
        if not engine.empty and theta is not None:
            before = len(engine.witnesses)
            tick = time.monotonic()
            member = engine.membership(theta)
            oracle_seconds += time.monotonic() - tick
            row_evaluations += total_rows
            new_witness = len(engine.witnesses) > before
            if new_witness:
                tick = time.monotonic()
                for j, (constant, q) in enumerate(rivals):
                    value = constant + scalar(q, theta)
                    lower[j] = value if lower[j] is None else max(lower[j], value)
                    witness_evaluations += 1
                bound_seconds += time.monotonic() - tick
        trace.append({
            "lpCall": invoked_lp_calls,
            "rivalIndex": selected,
            "lpStatus": solver_status,
            "rowsBefore": rows_before,
            "rowsAfter": len(engine.rows),
            "compatible": member,
            "newWitness": new_witness,
            "proposal": [str(x) for x in theta] if theta is not None else None,
            "supportUpperExact": str(proposed_upper),
            "dualProofIndices": new_proofs,
        })
        if engine.empty:
            stop_reason = "verified_empty"
            break
        if decision() != "unresolved":
            stop_reason = "threshold_decided"
            break
        if theta is None or member:
            # No fresh cut means repeating the same LP does not establish a
            # tighter exact proof. Try other rivals, retaining this valid bound.
            if selected is None:
                stop_reason = "unverified_nonemptiness"
                break
            stalled.add(selected)
        elif len(engine.rows) == rows_before and (selected is None or upper[selected] == old_upper):
            if selected is None:
                stop_reason = "separation_stalled"
                break
            stalled.add(selected)
        else:
            # A shared new cut may resolve a formerly stalled objective.
            stalled.clear()

    status = decision()
    if status == "unresolved" and time.monotonic() >= engine.deadline:
        stop_reason = "time_budget"
    lo, hi = bounds()
    if engine.empty:
        lo = hi = None
    comparisons = []
    for j, (constant, q) in enumerate(rivals):
        comparisons.append({
            "rivalIndex": j,
            "constantExact": str(constant),
            "objectiveExact": [str(x) for x in q],
            "lowerBound": outward(lower[j], False) if lower[j] is not None and not engine.empty else None,
            "upperBound": outward(upper[j], True) if not engine.empty else None,
            "lowerExact": str(lower[j]) if lower[j] is not None and not engine.empty else None,
            "upperExact": str(upper[j]) if not engine.empty else None,
            "upperProof": upper_proofs[j],
        })
    result = {
        "schema": "research-method-certificate.v1",
        "method": method,
        "status": status,
        "stopReason": stop_reason,
        "lowerBound": outward(lo, False) if lo is not None else None,
        "upperBound": outward(hi, True) if hi is not None else None,
        "lowerExact": str(lo) if lo is not None else None,
        "upperExact": str(hi) if hi is not None else None,
        "thresholdExact": str(threshold),
        "witnesses": [[str(x) for x in witness] for witness in engine.witnesses],
        "rivals": comparisons,
        "rows": [{"a": [str(x) for x in a], "b": str(b)} for a, b in engine.rows],
        "dualProofs": engine.dual_proofs,
        "trace": trace,
        "resources": {
            "lpCalls": invoked_lp_calls,
            "oracleCalls": engine.calls,
            "historyRows": total_rows,
            "rowsAdded": len(engine.rows),
            "cuts": len(engine.rows),
            "cumulativeLpRows": cumulative_lp_rows,
            "peakLpRows": peak_lp_rows,
            "historyRowEvaluations": row_evaluations,
            "witnessRivalEvaluations": witness_evaluations,
            "dualRivalEvaluations": dual_evaluations,
            "maxLpCalls": max_lp_calls,
            "maxSeconds": max_seconds,
            "solverSeconds": solver_seconds,
            "oracleSeconds": oracle_seconds,
            "boundSeconds": bound_seconds,
        },
        "policy": {
            "rowLoading": "full" if full else "lazy_one_most_violated_row_per_history",
            "rivalOrder": "adaptive_current_upper" if adaptive else
                          "original" if method == "lazy_sequential" else "static_initial_box_upper",
            "globalWitnessReuse": True,
            "globalDualReuse": method == "dual_reuse",
            "timeBudget": "cooperative_includes_setup",
            "fixedFeasibleCandidateAssumed": True,
        },
    }
    for key in ("parameterIds", "chosenDecision"):
        if key in problem:
            result[key] = problem[key]
    result["resources"]["elapsedSeconds"] = time.monotonic() - started
    result["resources"]["elapsedMs"] = round(result["resources"]["elapsedSeconds"] * 1000)
    return result
