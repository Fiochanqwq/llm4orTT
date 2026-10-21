"""Independent mechanism tests for the explicitly declared noise envelope.

These tests do not estimate a noise cap from fit residuals. Tiny two-parameter
examples have closed-form feasible sets and are also checked with the separate
exact polygon auditor. The deployment action is held fixed between endpoints.
"""
import copy
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solver"))
sys.path.insert(0, str(ROOT / "research"))

from inverse_sensitivity import analyze_with_sensitivity
from verify_comparison import verify_one


Q = Fraction


def sample(identifier="history", base=-0.2, decision=1):
    return {
        "id": identifier,
        "model": {
            "sense": "minimize",
            "variables": [{"name": "x", "type": "binary", "lower": 0, "upper": 1}],
            "objective": {"x": base},
            "constraints": [],
        },
        "features": {
            "theta": {"kind": "linear", "terms": {"x": 1}},
            "phi": {"kind": "linear", "terms": {"x": 0}},
        },
        "decision": {"x": decision},
    }


def case(upper=0.4, budget=0, threshold=0.1):
    result = {
        "schema": "contextual-inverse.v1",
        "hypotheses": [{"id": "theta", "lower": 0, "upper": 1},
                       {"id": "phi", "lower": 0, "upper": 1}],
        "samples": [sample()],
        "deployment": sample("deployment", base=-0.4),
        "lambda": 0,
        "pruneThreshold": 0,
        "certification": {
            "noise": {"kind": "absolute", "budget": budget},
            "threshold": threshold,
            "maxSeconds": 20,
            "maxOracleCalls": 100,
            "maxAssignments": 4096,
        },
    }
    if upper is not None:
        result["certification"]["sensitivity"] = {
            "upperNoise": {"kind": "absolute", "budget": upper},
            "maxSeconds": 20,
            "maxOracleCalls": 100,
        }
    return result


def analyze(data):
    return analyze_with_sensitivity(data, {"theta": 0, "phi": 0})


def independently_audit(data, full_result, truth=None):
    certificate = dict(full_result["decisionCertificate"])
    certificate["witnesses"] = full_result["witnesses"]
    return verify_one(data, certificate, truth)


class NoiseEnvelopeMechanismTests(unittest.TestCase):
    def test_no_upper_does_not_invent_or_validate_noise_budget(self):
        result = analyze(case(upper=None))
        self.assertEqual(result["decisionCertificate"]["status"], "safe")
        self.assertEqual(result["noiseSensitivity"]["status"], "not_requested")
        self.assertFalse(result["noiseSensitivity"]["rangeSafe"])
        self.assertIsNone(result["noiseSensitivity"]["upperNoise"])
        self.assertEqual(result["decisionGuidance"]["scope"], "nominal_budget_only")
        self.assertEqual(result["decisionGuidance"]["status"], "conditional_safe")
        self.assertFalse(result["assumptionAudit"]["trainingFitValidatesNoiseBudget"])
        self.assertEqual(result["assumptionAudit"]["noiseBudget"],
                         "declared_not_independently_verified")

    def test_underestimated_budget_exposes_risk_at_upper_endpoint(self):
        # U(0) has theta<=.2 and zero worst regret; U(.4) has theta<=.6,
        # giving exact worst regret .6-.4=.2 for the SAME x=1.
        data = case()
        result = analyze(data)
        sensitivity = result["noiseSensitivity"]
        self.assertEqual(result["decisionCertificate"]["status"], "safe")
        self.assertEqual(sensitivity["status"], "sensitive")
        self.assertFalse(sensitivity["rangeSafe"])
        self.assertEqual(sensitivity["upperCertificate"]["status"], "risk_witness")
        self.assertEqual(result["decisionGuidance"]["status"], "risk_witness")
        upper_data = copy.deepcopy(data)
        upper_data["certification"]["noise"] = sensitivity["upperNoise"]
        upper_audit = independently_audit(
            upper_data, sensitivity["upperAnalysis"], {"theta": "3/5", "phi": "1/2"})
        self.assertEqual(upper_audit["exactWorstRegretRational"], "1/5")
        self.assertEqual(upper_audit["exactTrueRegretRational"], "1/5")
        self.assertTrue(upper_audit["truthContained"])
        nominal_audit = independently_audit(data, result, {"theta": "3/5", "phi": "1/2"})
        self.assertFalse(nominal_audit["truthContained"])

    def test_safe_upper_transfers_to_nonempty_smaller_sets(self):
        result = analyze(case(upper=0.1))
        self.assertEqual(result["noiseSensitivity"]["status"], "stable_safe")
        self.assertTrue(result["noiseSensitivity"]["rangeSafe"])
        self.assertTrue(result["noiseSensitivity"]["fixedDecisionVerified"])
        self.assertEqual(result["decisionGuidance"]["scope"], "declared_upper_budget")
        self.assertEqual(result["decisionGuidance"]["status"], "conditional_safe")

    def test_exact_threshold_boundary_is_safe(self):
        # At upper=.3 the exact maximum is .1; binary serialization of .1
        # must not create a false risk label or remove a valid equality case.
        data = case(upper=0.3)
        result = analyze(data)
        sensitivity = result["noiseSensitivity"]
        self.assertEqual(sensitivity["status"], "stable_safe")
        upper_data = copy.deepcopy(data)
        upper_data["certification"]["noise"] = sensitivity["upperNoise"]
        audit = independently_audit(upper_data, sensitivity["upperAnalysis"])
        self.assertEqual(audit["exactWorstRegretRational"], "1/10")
        self.assertLessEqual(Q.from_float(sensitivity["upperCertificate"]["lowerBound"]), Q(1, 10))
        self.assertGreaterEqual(Q.from_float(sensitivity["upperCertificate"]["upperBound"]), Q(1, 10))

    def test_zero_and_equal_endpoints_are_valid(self):
        for delta in (0, 0.1, 0.4):
            with self.subTest(delta=delta):
                result = analyze(case(upper=delta, budget=delta))
                nominal = result["decisionCertificate"]
                upper = result["noiseSensitivity"]["upperCertificate"]
                self.assertEqual(nominal["chosenDecision"], upper["chosenDecision"])
                self.assertEqual(nominal["status"], upper["status"])
                self.assertEqual(nominal["lowerBound"], upper["lowerBound"])
                self.assertEqual(nominal["upperBound"], upper["upperBound"])

    def test_incompatible_nominal_can_have_safe_nonempty_upper(self):
        data = case(upper=0.3)
        data["samples"] = [sample("low", -0.2, 1), sample("high", -0.8, 0)]
        data["deployment"]["model"]["objective"]["x"] = -0.6
        result = analyze(data)
        self.assertEqual(result["decisionCertificate"]["status"], "incompatible")
        self.assertEqual(result["noiseSensitivity"]["status"], "stable_safe")
        self.assertTrue(result["noiseSensitivity"]["rangeSafe"])
        upper_data = copy.deepcopy(data)
        upper_data["certification"]["noise"] = {"kind": "absolute", "budget": 0.3}
        audit = independently_audit(upper_data, result["noiseSensitivity"]["upperAnalysis"])
        self.assertFalse(audit["feasibleSetEmpty"])
        self.assertEqual(audit["vertexCount"], 2)  # theta=.5; phi remains free.
        self.assertIn("不证明较小预算", result["decisionGuidance"]["note"])

    def test_empty_upper_is_never_vacuously_safe(self):
        data = case(upper=0.2)
        data["samples"] = [sample("low", -0.2, 1), sample("high", -0.8, 0)]
        result = analyze(data)
        self.assertEqual(result["decisionCertificate"]["status"], "incompatible")
        self.assertEqual(result["noiseSensitivity"]["status"], "incompatible")
        self.assertFalse(result["noiseSensitivity"]["rangeSafe"])
        self.assertEqual(result["decisionGuidance"]["status"], "incompatible")
        self.assertIsNone(result["noiseSensitivity"]["upperCertificate"]["upperBound"])

    def test_risk_at_both_endpoints_is_not_a_new_flip_claim(self):
        result = analyze(case(upper=0.5, budget=0.4))
        self.assertEqual(result["decisionCertificate"]["status"], "risk_witness")
        self.assertEqual(result["noiseSensitivity"]["status"], "risk_in_envelope")
        self.assertFalse(result["noiseSensitivity"]["criticalBudgetEstimated"])

    def test_no_upper_computation_evidence_blocks_range_safe(self):
        data = case(upper=0.1)
        data["certification"]["sensitivity"]["maxOracleCalls"] = 0
        result = analyze(data)
        self.assertEqual(result["decisionCertificate"]["status"], "safe")
        self.assertEqual(result["noiseSensitivity"]["upperCertificate"]["status"], "unresolved")
        self.assertEqual(result["noiseSensitivity"]["status"], "unresolved")
        self.assertEqual(result["decisionGuidance"]["status"], "unresolved")
        self.assertFalse(result["noiseSensitivity"]["rangeSafe"])

    def test_componentwise_budgets_accept_heterogeneous_envelope(self):
        data = case()
        data["samples"] = [sample("first"), sample("second", -0.8, 1)]
        data["certification"]["noise"] = {
            "kind": "absolute", "budgets": {"first": 0, "second": 0.2}}
        data["certification"]["sensitivity"]["upperNoise"] = {
            "kind": "absolute", "budgets": {"first": 0.4, "second": 0.3}}
        result = analyze(data)
        self.assertEqual(result["noiseSensitivity"]["status"], "sensitive")
        self.assertEqual(result["noiseSensitivity"]["upperNoise"]["budgets"],
                         {"first": 0.4, "second": 0.3})

    def test_componentwise_decrease_rejected_even_if_total_budget_increases(self):
        data = case()
        data["samples"] = [sample("first"), sample("second")]
        data["certification"]["noise"] = {
            "kind": "absolute", "budgets": {"first": 0.2, "second": 0.1}}
        data["certification"]["sensitivity"]["upperNoise"] = {
            "kind": "absolute", "budgets": {"first": 0.1, "second": 2.0}}
        with self.assertRaisesRegex(ValueError, "every history"):
            analyze(data)

    def test_missing_per_history_upper_budget_is_rejected(self):
        data = case()
        data["certification"]["sensitivity"]["upperNoise"] = {
            "kind": "absolute", "budgets": {"another-history": 0.4}}
        with self.assertRaises(ValueError):
            analyze(data)

    def test_invalid_or_ambiguous_upper_noise_is_rejected(self):
        invalid = [
            None, [], {"kind": "relative", "budget": 0.4},
            {"kind": "absolute"}, {"kind": "absolute", "budget": 0.4, "budgets": {}},
            {"kind": "absolute", "budget": -0.1},
            {"kind": "absolute", "budget": True},
            {"kind": "absolute", "budget": float("inf")},
            {"kind": "absolute", "budget": float("nan")},
            {"kind": "absolute", "budgets": []},
        ]
        for noise in invalid:
            with self.subTest(noise=noise):
                data = case()
                data["certification"]["sensitivity"]["upperNoise"] = noise
                with self.assertRaises(ValueError):
                    analyze(data)

    def test_invalid_resource_budgets_are_rejected(self):
        invalid = [
            ("maxSeconds", 0), ("maxSeconds", 121), ("maxSeconds", True),
            ("maxSeconds", float("nan")), ("maxOracleCalls", -1),
            ("maxOracleCalls", 10001), ("maxOracleCalls", 1.5),
            ("maxOracleCalls", True),
        ]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                data = case()
                data["certification"]["sensitivity"][key] = value
                with self.assertRaises(ValueError):
                    analyze(data)

    def test_no_upper_cannot_silently_invent_nominal_budget(self):
        data = case(upper=None)
        del data["certification"]
        result = analyze(data)
        self.assertEqual(result["status"], "budget_required")
        self.assertEqual(result["noiseSensitivity"]["status"], "not_requested")
        self.assertNotEqual(result["decisionGuidance"]["status"], "conditional_safe")

    def test_model_truth_box_assumption_is_not_repaired_by_larger_noise(self):
        data = case(upper=100)
        data["hypotheses"][0]["upper"] = 0.2
        result = analyze(data)
        self.assertEqual(result["noiseSensitivity"]["status"], "stable_safe")
        self.assertFalse(result["noiseSensitivity"]["budgetUpperBoundValidated"])
        self.assertEqual(result["assumptionAudit"]["modelStructure"],
                         "declared_not_independently_verified")
        upper_data = copy.deepcopy(data)
        upper_data["certification"]["noise"] = {"kind": "absolute", "budget": 100}
        audit = independently_audit(
            upper_data, result["noiseSensitivity"]["upperAnalysis"], {"theta": 1, "phi": 0})
        self.assertFalse(audit["truthContained"])
        self.assertEqual(audit["exactTrueRegretRational"], "3/5")
        self.assertEqual(audit["exactWorstRegretRational"], "0")

    def test_original_data_and_point_estimate_are_not_mutated(self):
        data, point = case(), {"theta": 0, "phi": 0}
        data_before, point_before = copy.deepcopy(data), copy.deepcopy(point)
        result = analyze_with_sensitivity(data, point)
        self.assertEqual(data, data_before)
        self.assertEqual(point, point_before)
        self.assertEqual(result["decisionCertificate"]["chosenDecision"],
                         result["noiseSensitivity"]["upperCertificate"]["chosenDecision"])
        result["noiseSensitivity"]["upperNoise"]["budget"] = 999
        self.assertEqual(data, data_before)

    def test_changed_candidate_blocks_range_transfer_even_when_endpoints_safe(self):
        nominal = {
            "decisionCertificate": {"status": "safe", "chosenDecision": {"x": 0}},
            "resources": {},
        }
        upper = {
            "decisionCertificate": {"status": "safe", "chosenDecision": {"x": 1}},
            "resources": {},
        }
        with patch("inverse_sensitivity.analyze_compatibility",
                   side_effect=[nominal, upper]):
            result = analyze(case())
        self.assertFalse(result["noiseSensitivity"]["fixedDecisionVerified"])
        self.assertFalse(result["noiseSensitivity"]["rangeSafe"])
        self.assertEqual(result["noiseSensitivity"]["status"], "unresolved")
        self.assertEqual(result["decisionGuidance"]["status"], "unresolved")

    def test_missing_candidate_blocks_range_transfer(self):
        nominal = {"decisionCertificate": {"status": "unresolved"}, "resources": {}}
        upper = {
            "decisionCertificate": {"status": "safe", "chosenDecision": {"x": 1}},
            "resources": {},
        }
        with patch("inverse_sensitivity.analyze_compatibility",
                   side_effect=[nominal, upper]):
            result = analyze(case())
        self.assertFalse(result["noiseSensitivity"]["rangeSafe"])
        self.assertEqual(result["decisionGuidance"]["status"], "unresolved")

    def test_core_unresolved_never_becomes_range_safe_by_matching_bounds_alone(self):
        endpoint = {
            "decisionCertificate": {"status": "unresolved", "chosenDecision": {"x": 1},
                                    "lowerBound": None, "upperBound": 0},
            "resources": {},
        }
        with patch("inverse_sensitivity.analyze_compatibility",
                   side_effect=[copy.deepcopy(endpoint), copy.deepcopy(endpoint)]):
            result = analyze(case())
        self.assertTrue(result["noiseSensitivity"]["fixedDecisionVerified"])
        self.assertFalse(result["noiseSensitivity"]["rangeSafe"])
        self.assertEqual(result["decisionGuidance"]["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
