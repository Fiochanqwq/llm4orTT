"""Correctness and actual basis-use checks for strengthened comparisons."""
import copy
import json
import sys
import time
import unittest
from fractions import Fraction as Q
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from certificate_methods import run_method as run_method_v1
from certificate_methods_v2 import METHODS, NEW_METHODS, _FullSimplexSet, run_method_v2
from comparison_cases import make_case, prepare_problem
from verify_comparison import prepare_case, verify_prepared
import test_certificate_methods as prior_checks
from test_certificate_methods import interval_problem


def two_support_problem():
    return {
        "box": [(Q(0), Q(1))] * 2,
        "histories": [[((Q(1), Q(0)), Q(2, 5)), ((Q(0), Q(1)), Q(2, 5))]],
        "rivals": [(Q(0), (Q(1), Q(0))), (Q(0), (Q(0), Q(1)))],
        "threshold": Q(2, 5),
    }


class StrengthenedMethodTests(unittest.TestCase):
    def audit(self, problem, result, exact):
        prior_checks.ComparisonMethodTests.audit(self, problem, result, exact)

    def test_every_budget_retains_exact_bounds(self):
        for method in NEW_METHODS:
            for budget in (0, 1, 2, 8, 32):
                for threshold in (Q(1, 10), Q(1, 5)):
                    with self.subTest(method=method, budget=budget, threshold=threshold):
                        problem = interval_problem(threshold)
                        result = run_method_v2(problem, method, budget, 5)
                        self.assertLessEqual(result["resources"]["lpCalls"], budget)
                        self.audit(problem, result, Q(1, 5))
                        expected = "risk_witness" if threshold == Q(1, 10) else "safe"
                        self.assertEqual(result["status"], "unresolved" if budget == 0 else expected)

    def test_warm_method_really_submits_previous_basis(self):
        problem = two_support_problem()
        warm = run_method_v2(problem, "full_warm_adaptive_dual", 8, 5)
        cold = run_method_v2(problem, "full_adaptive_dual", 8, 5)
        for result in (warm, cold):
            self.assertEqual(result["status"], "safe")
            self.assertEqual(result["resources"]["lpCalls"], 2)
            self.audit(problem, result, Q(2, 5))
            self.assertTrue(all(t["infoValid"] for t in result["solverTrace"]))
            self.assertTrue(all(t["simplexIterations"] >= 0 for t in result["solverTrace"]))
        self.assertEqual(warm["resources"]["modelBuilds"], 1)
        self.assertEqual(warm["resources"]["objectiveUpdates"], 1)
        self.assertEqual(warm["resources"]["basisAttempts"], 1)
        self.assertEqual(warm["resources"]["basisAccepted"], 1)
        self.assertTrue(warm["solverTrace"][1]["basisAccepted"])
        self.assertTrue(warm["solverTrace"][1]["modelReused"])
        self.assertEqual(cold["resources"]["modelBuilds"], 2)
        self.assertEqual(cold["resources"]["basisAccepted"], 0)

    def test_first_call_decision_does_not_claim_basis_reuse(self):
        result = run_method_v2(interval_problem(), "full_warm_adaptive_dual", 8, 5)
        self.assertEqual(result["status"], "risk_witness")
        self.assertEqual(result["resources"]["lpCalls"], 1)
        self.assertEqual(result["resources"]["basisAccepted"], 0)
        self.assertFalse(result["solverTrace"][0]["basisAttempted"])
        self.assertFalse(result["solverTrace"][0]["modelReused"])

    def test_missing_basis_has_explicit_fresh_model_fallback(self):
        problem = two_support_problem()
        engine = _FullSimplexSet(problem["box"], problem["histories"], 5, 8,
                                time.monotonic(), warm_start=True)
        for history in problem["histories"]:
            for a, b in history:
                engine.add_row(a, b)
        engine.lp_proposal((Q(1), Q(0)))
        engine.saved_basis = None
        theta, upper, _ = engine.lp_proposal((Q(0), Q(1)))
        self.assertTrue(engine.membership(theta))
        self.assertEqual(upper, Q(2, 5))
        self.assertEqual(engine.model_builds, 2)
        self.assertEqual(engine.basis_fallbacks, 1)
        self.assertEqual(engine.solver_trace[1]["fallback"], "no_valid_previous_basis")
        self.assertFalse(engine.solver_trace[1]["basisAccepted"])

    def test_empty_set_requires_rational_infeasibility_certificate(self):
        problem = interval_problem()
        problem["histories"] = [[((Q(1),), Q(1, 5))], [((Q(-1),), Q(-4, 5))]]
        for method in NEW_METHODS:
            result = run_method_v2(problem, method, 8, 5)
            self.assertEqual(result["status"], "incompatible")
            self.assertIsNone(result["lowerExact"])
            self.assertIsNone(result["upperExact"])
            self.assertTrue(any(
                all(Q(q) == 0 for q in p["sourceObjective"]) and Q(p["sourceUpperExact"]) < 0
                for p in result["dualProofs"]))

    def test_solver_infeasible_label_alone_does_not_certify(self):
        def proposal(engine, objective):
            return None, engine.box_support(objective), "unverified_infeasible"
        for method in NEW_METHODS:
            with patch.object(_FullSimplexSet, "lp_proposal", proposal):
                result = run_method_v2(interval_problem(), method, 8, 5)
            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["lowerExact"])

    def test_old_comparator_dispatch_preserves_substantive_results(self):
        for method in ("full_priority", "dual_reuse"):
            a = run_method_v1(two_support_problem(), method, 8, 5)
            b = run_method_v2(two_support_problem(), method, 8, 5)
            for field in ("method", "status", "lowerExact", "upperExact", "witnesses",
                          "rivals", "rows", "dualProofs", "trace", "policy"):
                self.assertEqual(a[field], b[field])
            self.assertEqual(b["implementationVersion"], "v1_unmodified_dispatched_by_v2")

    def test_independent_original_decision_verifier_accepts_new_methods(self):
        # This is a development-only mechanism seed, not an evaluation seed.
        case, tables = make_case("menu8", 17, 0.4, 0.4, "development")
        problem = prepare_problem(case, tables)
        prepared = prepare_case(case["input"], case["chosenDecision"], case["truth"])
        identifiers = [h["id"] for h in case["input"]["hypotheses"]]
        for method in NEW_METHODS:
            for budget in (0, 1, 2, 8):
                result = run_method_v2(problem, method, budget, 5)
                result["chosenDecision"] = case["chosenDecision"]
                result["thresholdRational"] = result["thresholdExact"]
                result["witnesses"] = [dict(zip(identifiers, w)) for w in result["witnesses"]]
                self.assertTrue(verify_prepared(prepared, result)["verified"])
                json.dumps(result, allow_nan=False)

    def test_truth_metadata_is_unused(self):
        a = two_support_problem()
        b = copy.deepcopy(a)
        b["truth"] = [-9999, 9999]
        for method in NEW_METHODS:
            x = run_method_v2(a, method, 8, 5)
            y = run_method_v2(b, method, 8, 5)
            for key in ("status", "lowerExact", "upperExact", "witnesses", "rivals", "dualProofs"):
                self.assertEqual(x[key], y[key])

    def test_setup_timeout_does_not_reset_solver_budget(self):
        for method in NEW_METHODS:
            result = run_method_v2(two_support_problem(), method, 8, 1e-12)
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual(result["stopReason"], "time_budget")
            self.assertEqual(result["resources"]["lpCalls"], 0)
            self.assertEqual(result["resources"]["modelBuilds"], 0)
            self.assertIsNone(result["lowerExact"])


if __name__ == "__main__":
    unittest.main()
