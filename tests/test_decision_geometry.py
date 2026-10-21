"""Independent known-answer cases for exact two-dimensional LP geometry."""
import json
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from decision_geometry import analyze_model, compare_models, compile_model, rational


def lp(objective=(1, 1), rows=(), sense="min"):
    return {"sense": sense, "objective": list(objective),
            "constraints": [{"a": list(a), "op": op, "b": b} for a, op, b in rows]}


BOX = [((1, 0), "<=", 2), ((0, 1), "<=", 3)]


class GeometryTests(unittest.TestCase):
    def test_known_triangle_and_exact_value(self):
        r = analyze_model(lp((3, 2), [((2, 3), "<=", 7)], "max"))
        self.assertEqual(r["vertices"], [["0", "0"], ["0", "7/3"], ["7/2", "0"]])
        self.assertEqual(r["value"], "21/2")
        self.assertEqual(r["optimal_face"]["vertices"], [["7/2", "0"]])

    def test_singleton_and_domain_constant_objective(self):
        rows = [((1, 0), "=", "1/3"), ((0, 1), "=", "2/7")]
        self.assertTrue(compare_models(lp((1, 0), rows), lp((0, -99), rows))["equivalent"])
        self.assertEqual(analyze_model(lp(rows=rows))["vertices"], [["1/3", "2/7"]])

    def test_line_segment(self):
        rows = [((1, 1), "=", 1)]
        r = analyze_model(lp((1, 1), rows))
        self.assertEqual(r["optimal_face"]["vertices"], [["0", "1"], ["1", "0"]])
        self.assertEqual(r["recession_rays"], [])

    def test_ray_with_finite_optimum_and_infinite_tie(self):
        rows = [((1, 0), "=", 2)]
        r = analyze_model(lp((1, 0), rows))
        self.assertEqual(r["status"], "optimal")
        self.assertEqual(r["optimal_face"]["recession_rays"], [["0", "1"]])
        self.assertEqual(analyze_model(lp((0, -1), rows))["status"], "unbounded")

    def test_slanted_recession_cone(self):
        r = analyze_model(lp((1, 1), [((1, -2), "<=", 0), ((-1, 1), "<=", 0)]))
        self.assertEqual(r["recession_rays"], [["1/2", "1/2"], ["2/3", "1/3"]])

    def test_empty(self):
        a = lp(rows=[((1, 0), "<=", -1)])
        b = lp(rows=[((0, 0), "<=", -1)])
        self.assertEqual(analyze_model(a)["status"], "infeasible")
        self.assertTrue(compare_models(a, b)["equivalent"])
        self.assertFalse(compare_models(a, lp())["equivalent"])

    def test_scaling_redundancy_and_sense(self):
        a = lp((1, 2), BOX)
        b = lp((-3, -6), BOX + [((2, 0), "<=", 4), ((1, 1), "<=", 5)], "max")
        self.assertTrue(compare_models(a, b)["equivalent"])

    def test_equal_optimum_different_feasible_set(self):
        r = compare_models(lp(rows=BOX), lp(rows=BOX + [((1, 1), "<=", 4)]))
        self.assertFalse(r["feasible_sets_equal"])
        self.assertTrue(r["optimal_faces_equal"])
        self.assertEqual(r["left"]["value"], r["right"]["value"])

    def test_optimal_face_mismatch_with_same_value(self):
        r = compare_models(lp((1, 0), BOX), lp((1, 1), BOX))
        self.assertTrue(r["feasible_sets_equal"])
        self.assertFalse(r["optimal_faces_equal"])
        self.assertTrue(any(w["point"] == ["0", "3"] for w in r["witnesses"]))

    def test_unbounded_inclusion_requires_finite_ray_witness(self):
        r = compare_models(lp(), lp(rows=[((1, 0), "<=", 1000000)]))
        self.assertFalse(r["feasible_sets_equal"])
        witness = next(w for w in r["witnesses"] if w["kind"] == "feasibility")
        self.assertEqual(witness["origin"], "ray")
        self.assertGreater(F(witness["point"][0]), 1000000)

    def test_every_witness_is_valid_and_ranked(self):
        a = lp((0, 1), [((1, -1), "<=", 2)])
        b = lp((1, 0), [((1, 0), "<=", 1), ((0, 1), "<=", 4)])
        r = compare_models(a, b)
        models = {"left": compile_model(a), "right": compile_model(b)}
        scores = []
        for w in r["witnesses"]:
            x, y = map(F, w["point"])
            self.assertTrue(all(u*x+v*y <= z for u,v,z in models[w["source"]].rows))
            row = w["target_row"]
            violation = F(row["a"][0])*x + F(row["a"][1])*y - F(row["b"])
            self.assertGreater(violation, 0)
            self.assertEqual(str(violation), w["violation"])
            if w["kind"] == "optimal_face":
                m = models[w["source"]]
                self.assertEqual(m.objective[0]*x+m.objective[1]*y, F(r[w["source"]]["value"]))
            scores.append(F(w["normalized_violation"]))
        self.assertEqual(scores, sorted(scores, reverse=True))
        json.dumps(r, allow_nan=False)

    def test_validation(self):
        for value in (True, float("nan"), float("inf"), "1/0", "__import__('os')", 2**129, "1"*129):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                rational(value)
        for bad in ({}, lp(rows=[((1, 0), "<", 1)]), lp(rows=BOX*17)):
            with self.assertRaises(ValueError):
                compile_model(bad)
        self.assertEqual(rational(0.1), F(1, 10))

    def test_same_optimal_face_is_not_same_preference_order(self):
        r = compare_models(lp((1, 1), BOX), lp((2, 1), BOX))
        self.assertTrue(r["equivalent"])
        self.assertTrue(r["optimal_faces_equal"])
        self.assertFalse(r["objective_order_equal"])
        self.assertTrue(compare_models(lp((1, 1), BOX), lp((-3, -3), BOX, "max"))["objective_order_equal"])

    def test_affine_hull_objective_restriction(self):
        rows = [((1, 1), "=", 1)]
        self.assertTrue(compare_models(lp((1, 0), rows), lp((7, 5), rows))["objective_order_equal"])
        self.assertFalse(compare_models(lp((1, 0), rows), lp((5, 7), rows))["objective_order_equal"])
        self.assertTrue(compare_models(lp((1, 1), rows), lp((0, 0), rows))["objective_order_equal"])
        self.assertFalse(compare_models(lp((1, 1), rows), lp((0, 1), rows))["objective_order_equal"])
        self.assertIsNone(compare_models(lp(), lp(rows=BOX))["objective_order_equal"])

    def test_objective_order_on_unbounded_face_uses_rays(self):
        self.assertFalse(compare_models(lp((1, 1)), lp((2, 1)))["objective_order_equal"])
        self.assertTrue(compare_models(lp((1, 1)), lp((2, 2)))["objective_order_equal"])

    def test_unknown_model_fields_are_not_silently_ignored(self):
        for name, value in (("integrality", [1, 1]), ("objective_offset", 7),
                            ("variables", ["integer", "binary"]), ("metadata", {})):
            model = lp()
            model[name] = value
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, "unknown model fields: " + name):
                compile_model(model)

    def test_missing_model_fields_are_explicit(self):
        for name in ("sense", "objective", "constraints"):
            model = lp()
            del model[name]
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, "missing model fields: " + name):
                compile_model(model)

    def test_unknown_and_missing_row_fields_are_explicit(self):
        for name in ("integrality", "strict", "label"):
            model = lp(rows=BOX)
            model["constraints"][0][name] = True
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, "constraint 0 unknown fields: " + name):
                compile_model(model)
        for name in ("a", "op", "b"):
            model = lp(rows=BOX)
            del model["constraints"][0][name]
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, "constraint 0 missing fields: " + name):
                compile_model(model)


if __name__ == "__main__":
    unittest.main()
