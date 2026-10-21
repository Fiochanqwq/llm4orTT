"""Strengthened full-row comparisons with measured HiGHS basis reuse.

Source lineage: ``certificate_methods.py`` supplies the exact input contract,
dual proof recorder, and untouched original comparators. This module reuses
those mechanisms and adapts its threshold loop for full-row adaptive dual reuse.
The persistent LP implementation follows ``inverse_certified.py``'s model and
exact proof checks, adding explicit simplex basis get/set calls and diagnostics.
No original source or frozen experiment artifact is modified.

The two new methods have identical row loading, rival scheduling, witness reuse,
and dual reuse. They differ only in LP state reuse. A first-call decision has no
opportunity to reuse a basis and is recorded that way. A valid basis accepted by
HiGHS is evidence of an actual warm-start submission, not a speedup guarantee.
"""
import math
import time
from fractions import Fraction as Q

import highspy as hs
import numpy as np

from certificate_methods import _AuditSet, _normalize, run_method as run_method_v1
from inverse_certified import outward, scalar


NEW_METHODS = ("full_adaptive_dual", "full_warm_adaptive_dual")
METHODS = ("full_priority", "dual_reuse") + NEW_METHODS


class _FullSimplexSet(_AuditSet):
    """Full-row LPs with exact checks and optional persistent solver state."""

    def __init__(self, *args, warm_start=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.warm_start = warm_start
        self.solver = None
        self.saved_basis = None
        self.model_row_count = None
        self.solver_trace = []
        self.model_builds = 0
        self.objective_updates = 0
        self.basis_attempts = 0
        self.basis_accepted = 0
        self.basis_fallbacks = 0

    def _new_solver(self, objective):
        solver = hs.Highs()
        for key, value in {
            "output_flag": False, "threads": 1, "solver": "simplex",
            "parallel": "off", "presolve": "on",
            "primal_feasibility_tolerance": 1e-9,
            "dual_feasibility_tolerance": 1e-9,
        }.items():
            status = solver.setOptionValue(key, value)
            if status != hs.HighsStatus.kOk:
                raise RuntimeError("HiGHS rejected solver option " + key + ": " + str(status))
        lp = hs.HighsLp()
        lp.num_col_, lp.num_row_ = self.dimension, len(self.rows)
        lp.col_cost_ = [-float(v) for v in objective]
        lp.col_lower_ = [float(lo) for lo, _ in self.box]
        lp.col_upper_ = [float(hi) for _, hi in self.box]
        lp.row_lower_ = [-hs.kHighsInf] * len(self.rows)
        lp.row_upper_ = [float(b) for _, b in self.rows]
        starts, indices, values = [0], [], []
        for a, _ in self.rows:
            for j, value in enumerate(a):
                if value:
                    indices.append(j)
                    values.append(float(value))
            starts.append(len(indices))
        lp.a_matrix_.format_ = hs.MatrixFormat.kRowwise
        lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = starts, indices, values
        status = solver.passModel(lp)
        if status != hs.HighsStatus.kOk:
            raise RuntimeError("HiGHS rejected LP model: " + str(status))
        self.model_builds += 1
        return solver

    def lp_proposal(self, objective):
        reused_model = self.warm_start and self.solver is not None and self.model_row_count == len(self.rows)
        basis_available = False
        basis_attempted = False
        basis_accepted = False
        fallback = None
        set_basis_status = None
        if reused_model:
            solver = self.solver
            status = solver.changeColsCost(
                self.dimension,
                np.arange(self.dimension, dtype=np.int32),
                np.array([-float(v) for v in objective], dtype=np.float64),
            )
            if status != hs.HighsStatus.kOk:
                raise RuntimeError("HiGHS rejected objective update: " + str(status))
            self.objective_updates += 1
            basis_available = bool(
                self.saved_basis is not None and self.saved_basis.valid
                and len(self.saved_basis.col_status) == self.dimension
                and len(self.saved_basis.row_status) == len(self.rows))
            if basis_available:
                basis_attempted = True
                self.basis_attempts += 1
                status = solver.setBasis(self.saved_basis)
                set_basis_status = str(status)
                basis_accepted = status == hs.HighsStatus.kOk and solver.getBasis().valid
                if basis_accepted:
                    self.basis_accepted += 1
                else:
                    fallback = "basis_submission_not_accepted"
            else:
                fallback = "no_valid_previous_basis"
            if fallback:
                # Use a genuinely fresh LP on failed/missing basis instead of
                # silently treating incidental retained state as a warm start.
                solver = self._new_solver(objective)
                self.basis_fallbacks += 1
                reused_model = False
        else:
            if self.warm_start and self.solver is not None:
                fallback = "row_structure_changed"
                self.basis_fallbacks += 1
            solver = self._new_solver(objective)
        if self.warm_start:
            self.solver = solver
            self.model_row_count = len(self.rows)
        solver.setOptionValue("time_limit", max(.001, self.deadline - time.monotonic()))
        run_status = solver.run()
        self.lp_calls += 1
        status = solver.getModelStatus()
        solution = solver.getSolution()
        info = solver.getInfo()
        returned_basis = solver.getBasis()
        if self.warm_start:
            self.saved_basis = returned_basis if returned_basis.valid else None
        self.solver_trace.append({
            "lpCall": self.lp_calls,
            "solverRunStatus": str(run_status),
            "modelReused": bool(reused_model),
            "basisAvailable": basis_available,
            "basisAttempted": basis_attempted,
            "basisAccepted": bool(basis_accepted),
            "setBasisStatus": set_basis_status,
            "basisValidAfter": bool(returned_basis.valid),
            "fallback": fallback,
            "infoValid": bool(info.valid),
            "simplexIterations": int(info.simplex_iteration_count) if info.valid else None,
            "ipmIterations": int(info.ipm_iteration_count) if info.valid else None,
            "crossoverIterations": int(info.crossover_iteration_count) if info.valid else None,
        })
        upper = self.box_support(objective)
        if solution.dual_valid:
            multipliers = [max(Q(0), -Q.from_float(float(v))) for v in solution.row_dual]
            upper = min(upper, self.dual_upper(objective, multipliers))
        if status == hs.HighsModelStatus.kInfeasible:
            _, exists, ray = solver.getDualRay()
            if exists:
                for sign in (1, -1):
                    multipliers = [max(Q(0), sign * Q.from_float(float(v))) for v in ray]
                    if self.dual_upper([Q(0)] * self.dimension, multipliers) < 0:
                        self.empty = True
                        break
        theta = self.reconstruct(solution.col_value) if solution.value_valid else None
        return theta, upper, str(status)


def run_method_v2(problem, method, max_lp_calls, max_seconds):
    """Dispatch old comparators unchanged or run strengthened full-row methods.

    Exact validation, full-row insertion, model construction, objective updates,
    solver runs, proof arithmetic and result assembly are inside the wall timer.
    The wall limit is cooperative; an in-flight exact operation can overrun it.
    """
    started = time.monotonic()
    if method in ("full_priority", "dual_reuse"):
        result = run_method_v1(problem, method, max_lp_calls, max_seconds)
        result["implementationVersion"] = "v1_unmodified_dispatched_by_v2"
        result["resources"]["dispatchElapsedSeconds"] = time.monotonic() - started
        return result
    if method not in NEW_METHODS:
        raise ValueError("Unknown v2 method: " + str(method))
    if isinstance(max_lp_calls, bool) or not isinstance(max_lp_calls, int) or max_lp_calls < 0:
        raise ValueError("max_lp_calls must be a nonnegative integer")
    if (isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds) or max_seconds <= 0):
        raise ValueError("max_seconds must be finite and positive")
    box, histories, rivals, threshold = _normalize(problem)
    engine = _FullSimplexSet(
        box, histories, max_seconds, max_lp_calls, started,
        warm_start=method == "full_warm_adaptive_dual")
    upper = [constant + engine.box_support(q) for constant, q in rivals]
    lower = [None] * len(rivals)
    upper_proofs = [{"kind": "box"} for _ in rivals]
    total_rows = sum(map(len, histories))
    solver_seconds = oracle_seconds = bound_seconds = 0.0
    row_evaluations = witness_evaluations = dual_evaluations = 0
    cumulative_lp_rows = peak_lp_rows = invoked_lp_calls = 0
    trace, stalled = [], set()
    stop_reason = "lp_budget"
    setup_complete = True
    for history in histories:
        for a, b in history:
            if time.monotonic() >= engine.deadline:
                setup_complete = False
                break
            engine.add_row(a, b)
        if not setup_complete:
            break
    setup_seconds = time.monotonic() - started

    def bounds():
        lo = max([Q(0)] + [v for v in lower if v is not None]) if engine.witnesses else None
        return lo, max([Q(0)] + upper)

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
        unresolved = [j for j in range(len(rivals)) if upper[j] > threshold and j not in stalled]
        if unresolved:
            selected = max(unresolved, key=lambda j: (upper[j], -j))
            objective = rivals[selected][1]
        elif not engine.witnesses:
            selected, objective = None, tuple(Q(0) for _ in box)
        else:
            stop_reason = "unresolved_numerical_gap"
            break
        rows_before, proof_start = len(engine.rows), len(engine.dual_proofs)
        tick = time.monotonic()
        invoked_lp_calls += 1
        theta, proposed_upper, solver_status = engine.lp_proposal(objective)
        solver_seconds += time.monotonic() - tick
        cumulative_lp_rows += rows_before
        peak_lp_rows = max(peak_lp_rows, rows_before)
        tick = time.monotonic()
        new_proofs = list(range(proof_start, len(engine.dual_proofs)))
        # Each valid vector proves every rival bound. The box is retained when
        # a vector gives a weaker result; missing proofs never tighten a bound.
        if not engine.empty:
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
        member, new_witness = None, False
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
            "lpCall": invoked_lp_calls, "rivalIndex": selected,
            "lpStatus": solver_status, "rowsBefore": rows_before,
            "rowsAfter": len(engine.rows), "compatible": member,
            "newWitness": new_witness,
            "proposal": [str(x) for x in theta] if theta is not None else None,
            "supportUpperExact": str(proposed_upper), "dualProofIndices": new_proofs,
        })
        if decision() != "unresolved":
            stop_reason = "verified_empty" if engine.empty else "threshold_decided"
            break
        if selected is None:
            stop_reason = "unverified_nonemptiness"
            break
        # Full rows are present already. A missing/unhelpful numerical proposal
        # cannot be cured by repeatedly solving the identical support LP.
        stalled.add(selected)
    status = decision()
    if status == "unresolved" and time.monotonic() >= engine.deadline:
        stop_reason = "time_budget"
    lo, hi = bounds()
    if engine.empty:
        lo = hi = None
    comparisons = [{
        "rivalIndex": j, "constantExact": str(constant),
        "objectiveExact": [str(x) for x in q],
        "lowerBound": outward(lower[j], False) if lower[j] is not None and not engine.empty else None,
        "upperBound": outward(upper[j], True) if not engine.empty else None,
        "lowerExact": str(lower[j]) if lower[j] is not None and not engine.empty else None,
        "upperExact": str(upper[j]) if not engine.empty else None,
        "upperProof": upper_proofs[j],
    } for j, (constant, q) in enumerate(rivals)]
    result = {
        "schema": "research-method-certificate.v1",
        "implementationVersion": "v2_full_rows_adaptive_dual",
        "method": method, "status": status, "stopReason": stop_reason,
        "lowerBound": outward(lo, False) if lo is not None else None,
        "upperBound": outward(hi, True) if hi is not None else None,
        "lowerExact": str(lo) if lo is not None else None,
        "upperExact": str(hi) if hi is not None else None,
        "thresholdExact": str(threshold),
        "witnesses": [[str(x) for x in witness] for witness in engine.witnesses],
        "rivals": comparisons,
        "rows": [{"a": [str(x) for x in a], "b": str(b)} for a, b in engine.rows],
        "dualProofs": engine.dual_proofs, "trace": trace,
        "solverTrace": engine.solver_trace,
        "resources": {
            "lpCalls": invoked_lp_calls, "oracleCalls": engine.calls,
            "historyRows": total_rows, "rowsAdded": len(engine.rows), "cuts": len(engine.rows),
            "cumulativeLpRows": cumulative_lp_rows, "peakLpRows": peak_lp_rows,
            "historyRowEvaluations": row_evaluations,
            "witnessRivalEvaluations": witness_evaluations,
            "dualRivalEvaluations": dual_evaluations,
            "maxLpCalls": max_lp_calls, "maxSeconds": max_seconds,
            "setupSeconds": setup_seconds, "solverSeconds": solver_seconds,
            "oracleSeconds": oracle_seconds, "boundSeconds": bound_seconds,
            "modelBuilds": engine.model_builds, "objectiveUpdates": engine.objective_updates,
            "basisAttempts": engine.basis_attempts, "basisAccepted": engine.basis_accepted,
            "basisFallbacks": engine.basis_fallbacks,
            "simplexIterations": sum(t["simplexIterations"] or 0 for t in engine.solver_trace),
        },
        "policy": {
            "rowLoading": "full", "rivalOrder": "adaptive_current_upper",
            "globalWitnessReuse": True, "globalDualReuse": True,
            "persistentSimplex": engine.warm_start, "presolve": "on",
            "basisReuse": "explicit_setBasis_with_status_and_validity_check" if engine.warm_start else "none",
            "timeBudget": "cooperative_includes_validation_setup_lp_proofs_and_result_assembly",
            "fixedFeasibleCandidateAssumed": True,
            "sourceLineage": ["research/certificate_methods.py", "solver/inverse_certified.py"],
        },
    }
    for key in ("parameterIds", "chosenDecision"):
        if key in problem:
            result[key] = problem[key]
    result["resources"]["elapsedSeconds"] = time.monotonic() - started
    result["resources"]["elapsedMs"] = round(result["resources"]["elapsedSeconds"] * 1000)
    return result
