"""Independent mechanism checks for the bounded-noise reference certificate.

Run from the workspace root:
    resources/runtime/python/python.exe -m unittest discover -s tests -v

Expected intervals and regrets below are derived directly from the one-variable
costs, rather than by calling the implementation's affine/canonical helpers.
These checks establish numerical and logical correctness on small cases; they
are not an external-validity or publication-readiness experiment.
"""
import copy
import math
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solver"))

from inverse import validate
from inverse_certified import (
    CompatibleSet,
    analyze_compatibility,
    exact_solve,
    outward,
)
from inverse_local import analyze

Q = Fraction


def sample(identifier="history", base=-0.4, feature=1, decision=1,
           variable_type="binary", lower=0, upper=1):
    return {
        "id": identifier,
        "model": {
            "sense": "minimize",
            "variables": [{
                "name": "x", "type": variable_type,
                "lower": lower, "upper": upper,
            }],
            "objective": {"x": base},
            "constraints": [],
        },
        "features": {"theta": {"kind": "linear", "terms": {"x": feature}}},
        "decision": {"x": decision},
    }


def case(histories=None, deployment=None, budget=0.4, threshold=0.1,
         max_calls=100):
    result = {
        "schema": "contextual-inverse.v1",
        "hypotheses": [{"id": "theta", "lower": 0, "upper": 1}],
        "samples": histories if histories is not None else [sample()],
        "lambda": 0,
        "pruneThreshold": 0,
        "certification": {
            "noise": {"kind": "absolute", "budget": budget},
            "threshold": threshold,
            "maxSeconds": 20,
            "maxOracleCalls": max_calls,
            "maxAssignments": 4096,
        },
    }
    if deployment is not None:
        result["deployment"] = deployment
    return result


class CertificateMechanismTests(unittest.TestCase):
    def assert_encloses(self, certificate, exact_regret):
        """Compare exact binary floats with the independently known rational."""
        if certificate["lowerBound"] is not None:
            self.assertLessEqual(Q.from_float(certificate["lowerBound"]), exact_regret)
        if certificate["upperBound"] is not None:
            self.assertGreaterEqual(Q.from_float(certificate["upperBound"]), exact_regret)

    def test_noisy_history_compatible_interval_retains_truth(self):
        # g(theta)=max(0,theta-.4), so g<=.4 means theta in [0,.8].
        result = analyze_compatibility(case(), {"theta": 0})
        interval = result["ranges"][0]
        self.assertAlmostEqual(interval["lower"], 0)
        self.assertAlmostEqual(interval["upper"], 0.8)
        self.assertLessEqual(interval["lower"], 0.8)
        self.assertGreaterEqual(interval["upper"], 0.8)
        for witness in result["witnesses"]:
            theta = Q(witness["theta"])
            self.assertTrue(0 <= theta <= Q(4, 5))
        self.assertEqual(result["historyActionCounts"], [2])
        self.assertEqual(result["deploymentActionCount"], 2)

    def test_empirical_fit_and_declared_noise_set_stay_distinct(self):
        # An exact old loss minimizer excludes .8, but the declared budget need not.
        data = case()
        data["maxIterations"] = 40.0
        result = analyze(data)
        empirical = result["analysis"]["identification"]["ranges"][0]
        compatible = result["analysis"]["compatibility"]["ranges"][0]
        self.assertEqual(empirical["status"], "optimal")
        self.assertLess(empirical["upper"], 0.401)
        self.assertGreaterEqual(compatible["upper"], 0.8)

    def test_ambiguous_parameters_can_still_have_safe_action(self):
        # With theta<=.8, (theta-1)x is minimized by x=1 for every parameter.
        data = case(deployment=sample("deployment", base=-1), threshold=0)
        result = analyze_compatibility(data, {"theta": 0})
        certificate = result["decisionCertificate"]
        self.assertEqual(certificate["status"], "safe")
        self.assertEqual(certificate["chosenDecision"], {"x": 1})
        self.assertGreater(result["ranges"][0]["upper"] - result["ranges"][0]["lower"], 0.7)
        self.assert_encloses(certificate, Q(0))
        self.assertEqual(certificate["upperBound"], 0)

    def test_conflicting_deployment_preferences_yield_risk_witness(self):
        # Selected x=1 has worst regret .8-.6=.2, attained at theta=.8.
        data = case(deployment=sample("deployment", base=-0.6), threshold=0.1)
        result = analyze_compatibility(data, {"theta": 0})
        certificate = result["decisionCertificate"]
        self.assertEqual(certificate["status"], "risk_witness")
        self.assertEqual(certificate["chosenDecision"], {"x": 1})
        self.assert_encloses(certificate, Q(1, 5))
        self.assertAlmostEqual(certificate["lowerBound"], 0.2)
        self.assertAlmostEqual(certificate["upperBound"], 0.2)
        self.assertTrue(any(
            max(Q(0), Q(w["theta"]) - Q(3, 5)) > Q(1, 10)
            for w in result["witnesses"]
        ))

    def test_joint_coupling_is_preserved_beyond_coordinate_box(self):
        # History gives theta+phi<=1; both coordinate projections are [0,1].
        # For deployment cost (theta+phi-1.5)x, x=1 is nevertheless always safe.
        history = sample(base=-1)
        history["features"]["phi"] = {"kind": "linear", "terms": {"x": 1}}
        deployment = copy.deepcopy(history)
        deployment["id"] = "deployment"
        deployment["model"]["objective"] = {"x": -1.5}
        data = case(histories=[history], deployment=deployment, budget=0, threshold=0)
        data["hypotheses"].append({"id": "phi", "lower": 0, "upper": 1})
        result = analyze_compatibility(data, {"theta": 0, "phi": 0})
        for interval in result["ranges"]:
            self.assertAlmostEqual(interval["lower"], 0)
            self.assertAlmostEqual(interval["upper"], 1)
        for witness in result["witnesses"]:
            self.assertLessEqual(Q(witness["theta"]) + Q(witness["phi"]), 1)
        self.assertEqual(result["decisionCertificate"]["status"], "safe")
        self.assertEqual(result["decisionCertificate"]["upperBound"], 0)
        # Evaluating the coordinate box as though it were joint would give .5.
        self.assertEqual(Q(1) + Q(1) - Q(3, 2), Q(1, 2))

    def test_anytime_bounds_remain_valid_at_every_small_oracle_budget(self):
        for budget in range(9):
            with self.subTest(max_calls=budget):
                data = case(
                    deployment=sample("deployment", base=-0.6),
                    threshold=0.1, max_calls=budget,
                )
                result = analyze_compatibility(data, {"theta": 0})
                certificate = result["decisionCertificate"]
                self.assert_encloses(certificate, Q(1, 5))
                self.assertLessEqual(result["resources"]["oracleCalls"], budget)
                self.assertNotEqual(certificate["status"], "safe")

    def test_zero_oracle_budget_does_not_certify_unverified_nonempty_set(self):
        data = case(
            deployment=sample("deployment", base=-1),
            threshold=0, max_calls=0,
        )
        result = analyze_compatibility(data, {"theta": 0})
        self.assertEqual(result["decisionCertificate"]["status"], "unresolved")
        self.assertIsNone(result["decisionCertificate"]["lowerBound"])
        self.assertEqual(result["resources"]["oracleCalls"], 0)
        self.assertEqual(result["resources"]["lpCalls"], 0)
        self.assertEqual(result["witnesses"], [])

    def test_contradictory_exact_histories_have_verified_empty_set(self):
        # x=1 at cost theta-.2 requires theta<=.2.
        # x=0 at cost theta-.8 requires theta>=.8.
        histories = [
            sample("low", base=-0.2, decision=1),
            sample("high", base=-0.8, decision=0),
        ]
        result = analyze_compatibility(case(histories=histories, budget=0))
        self.assertEqual(result["status"], "incompatible")
        self.assertEqual(result["decisionCertificate"]["status"], "incompatible")
        self.assertIsNone(result["decisionCertificate"]["lowerBound"])
        self.assertIsNone(result["decisionCertificate"]["upperBound"])
        self.assertEqual(result["witnesses"], [])

    def test_unverified_infeasible_solver_label_does_not_prove_empty_set(self):
        # Emulate an LP outcome with no exact infeasibility proof and no point.
        def unverified_proposal(engine, objective):
            return None, engine.box_support(objective), "HighsModelStatus.kInfeasible"

        with patch.object(CompatibleSet, "lp_proposal", unverified_proposal):
            result = analyze_compatibility(case(), {"theta": 0})
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["decisionCertificate"]["status"], "unresolved")
        self.assertEqual(result["witnesses"], [])
        self.assertNotEqual(result["status"], "incompatible")

    def test_deployment_decision_is_not_used_as_history(self):
        # Either deployment decision field must leave U=[0,.8] unchanged.
        left = analyze_compatibility(case(
            deployment=sample("deployment", base=-0.9, decision=0)), {"theta": 0})
        right = analyze_compatibility(case(
            deployment=sample("deployment", base=-0.9, decision=1)), {"theta": 0})
        self.assertEqual(left["ranges"], right["ranges"])
        self.assertEqual(left["decisionCertificate"], right["decisionCertificate"])
        self.assertEqual(left["deploymentSource"], "provided_context")

    def test_budget_underestimate_is_not_claimed_to_cover_hidden_truth(self):
        result = analyze_compatibility(case(budget=0))
        self.assertLess(result["ranges"][0]["upper"], 0.401)
        self.assertTrue(any("绝对费用误差预算" in text for text in result["assumptions"]))
        self.assertIn("不是置信区间", result["meaning"])

    def test_certificate_is_conditional_on_box_and_feature_completeness(self):
        data = case(deployment=sample("deployment", base=-1), threshold=0)
        result = analyze_compatibility(data, {"theta": 0})
        self.assertEqual(result["decisionCertificate"]["status"], "safe")
        # Outside the stated parameter box, theta=1.2 gives regret .2.
        self.assertEqual(max(Q(0), Q(6, 5) - 1), Q(1, 5))
        # An omitted extra feature cost x similarly invalidates this model.
        self.assertEqual(max(Q(0), Q(2, 5) - 1 + 1), Q(2, 5))
        self.assertTrue(any("参数框" in text for text in result["assumptions"]))
        self.assertTrue(any("特征正确且完整" in text for text in result["assumptions"]))
        self.assertIn("假设", result["decisionCertificate"]["note"])

    def test_hidden_truth_metadata_never_changes_certificate(self):
        data = case(deployment=sample("deployment", base=-0.6))
        other = copy.deepcopy(data)
        other["truth"] = {"theta": 999}
        other["heldOutTruth"] = {"theta": -123}
        a = analyze_compatibility(data, {"theta": 0})
        b = analyze_compatibility(other, {"theta": 0})
        self.assertEqual(a["ranges"], b["ranges"])
        self.assertEqual(a["decisionCertificate"], b["decisionCertificate"])
        self.assertEqual(a["witnesses"], b["witnesses"])

    def test_soft_hinge_is_evaluated_at_actual_original_decision(self):
        for sense, base in [("<=", -1), (">=", 1)]:
            with self.subTest(sense=sense):
                history = sample(
                    base=base, decision=1, variable_type="integer",
                    lower=0, upper=2,
                )
                history["features"]["theta"] = {
                    "kind": "soft", "terms": {"x": 1}, "sense": sense, "rhs": 1,
                }
                data = case(histories=[history], budget=0, threshold=0)
                data["hypotheses"][0]["upper"] = 3
                result = analyze_compatibility(data, {"theta": 2})
                self.assertAlmostEqual(result["ranges"][0]["lower"], 1)
                self.assertAlmostEqual(result["ranges"][0]["upper"], 3)
                self.assertEqual(result["decisionCertificate"]["chosenDecision"], {"x": 1})
                self.assertEqual(result["decisionCertificate"]["status"], "safe")
                self.assertEqual(result["decisionCertificate"]["upperBound"], 0)
                self.assertEqual(result["historyActionCounts"], [3])

    def test_assignment_cap_refuses_partial_enumeration(self):
        data = case()
        data["certification"]["maxAssignments"] = 1
        result = analyze_compatibility(data)
        self.assertEqual(result["status"], "unsupported")
        self.assertNotIn("decisionCertificate", result)
        self.assertIn("完整枚举", result["note"])

    def test_unbounded_integer_domain_is_explicitly_unsupported(self):
        data = case(histories=[sample(variable_type="integer", upper=None)])
        result = analyze_compatibility(data)
        self.assertEqual(result["status"], "unsupported")
        self.assertNotIn("decisionCertificate", result)

    def test_continuous_domain_is_explicitly_unsupported(self):
        result = analyze_compatibility(case(
            histories=[sample(variable_type="continuous")]))
        self.assertEqual(result["status"], "unsupported")
        self.assertNotIn("decisionCertificate", result)

    def test_enumeration_timeout_has_no_unearned_safety_bound(self):
        data = case()
        data["certification"]["maxSeconds"] = 1
        with patch("inverse_certified.time.monotonic", side_effect=[0, 2]):
            result = analyze_compatibility(data)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["decisionCertificate"]["status"], "unresolved")
        self.assertIsNone(result["decisionCertificate"]["upperBound"])

    def test_relative_noise_is_not_silently_treated_as_absolute(self):
        data = case()
        data["certification"]["noise"] = {"kind": "relative", "budget": 0.1}
        result = analyze_compatibility(data)
        self.assertEqual(result["status"], "unsupported")
        self.assertNotIn("decisionCertificate", result)

    def test_missing_budget_has_distinct_status(self):
        data = case()
        del data["certification"]
        result = analyze_compatibility(data)
        self.assertEqual(result["status"], "budget_required")
        self.assertNotIn("decisionCertificate", result)

    def test_per_history_budget_must_be_explicit_for_each_observation(self):
        data = case()
        data["certification"]["noise"] = {"kind": "absolute", "budgets": {}}
        with self.assertRaisesRegex(ValueError, "每条历史"):
            analyze_compatibility(data)

    def test_infeasible_or_nonintegral_history_is_rejected(self):
        for decision in [0.5, 2]:
            with self.subTest(decision=decision):
                with self.assertRaisesRegex(ValueError, "历史决策"):
                    analyze_compatibility(case(histories=[sample(decision=decision)]))

    def test_integer_valued_float_iteration_limit_is_valid(self):
        data = case()
        data["maxIterations"] = 40.0
        self.assertIs(validate(data), data)
        result = analyze(data)
        self.assertEqual(
            result["analysis"]["identification"]["ranges"][0]["status"], "optimal")


class ExactCertificateArithmeticTests(unittest.TestCase):
    def test_any_nonnegative_dual_multiplier_gives_valid_upper_bound(self):
        # Max theta subject to 0<=theta<=1 and theta<=4/5 is 4/5.
        engine = CompatibleSet([(Q(0), Q(1))], [], max_calls=0)
        engine.add_row((Q(1),), Q(4, 5))
        for multiplier in [Q(0), Q(1, 3), Q(999999999, 1000000000), Q(1), Q(5)]:
            with self.subTest(multiplier=multiplier):
                self.assertGreaterEqual(
                    engine.dual_upper((Q(1),), [multiplier]), Q(4, 5))
        self.assertEqual(engine.dual_upper((Q(1),), [Q(1)]), Q(4, 5))
        # Tiny dual residual is paid at its worst box endpoint.
        self.assertGreater(
            engine.dual_upper((Q(1),), [Q(999999999, 1000000000)]), Q(4, 5))

    def test_incompatibility_requires_a_strictly_negative_exact_bound(self):
        engine = CompatibleSet([(Q(0), Q(1))], [], max_calls=0)
        engine.add_row((Q(1),), Q(1, 5))
        engine.add_row((Q(-1),), Q(-4, 5))
        self.assertEqual(
            engine.dual_upper((Q(0),), [Q(1), Q(1)]), Q(-3, 5))

    def test_rational_vertex_reconstruction_handles_fractional_boundary(self):
        vertex = exact_solve(
            [(Q(3), Q(0)), (Q(1), Q(2))],
            [Q(1), Q(1)], 2,
        )
        self.assertEqual(vertex, (Q(1, 3), Q(1, 3)))
        engine = CompatibleSet([(Q(0), Q(1))], [], max_calls=0)
        engine.add_row((Q(3),), Q(1))
        rebuilt = engine.reconstruct([float(Q(1, 3))])
        self.assertEqual(rebuilt, (Q(1, 3),))
        self.assertTrue(engine.inside_outer(rebuilt))

    def test_outward_serialization_never_rounds_a_bound_inward(self):
        for value in [Q(1, 3), Q(-1, 3), Q(1, 10), Q(-1, 10), Q(0)]:
            with self.subTest(value=value):
                self.assertGreaterEqual(Q.from_float(outward(value, True)), value)
                self.assertLessEqual(Q.from_float(outward(value, False)), value)
                self.assertTrue(math.isfinite(outward(value, True)))


if __name__ == "__main__":
    unittest.main()
