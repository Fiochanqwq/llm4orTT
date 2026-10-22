"""No-network tests of information isolation and scoring, using temporary data."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import decision_contract_study as study


BOX = {"sense": "min", "objective": ["1", "1"], "constraints": [
    {"a": ["1", "0"], "op": "<=", "b": "2"},
    {"a": ["0", "1"], "op": "<=", "b": "3"}]}


def case(identifier="731"):
    return {"id": identifier, "text": "Make apples and pears under the stated budgets.",
            "variables": ["apples", "pears"], "split": "heldout",
            "reference": deepcopy(BOX), "private_secret": "PRIVATE_REFERENCE_SENTINEL",
            "source_objective_direction": "PRIVATE_DIRECTION_SENTINEL"}


class ProtocolTests(unittest.TestCase):
    def test_public_paper_ladder_cells_replay_from_derived_outcomes(self):
        from replay import read, exact_binomial_interval
        root = study.ROOT / 'research/artifacts/decision-contract-20261022'
        data = read(root / 'results.json')
        cases, observations = data['ladder_cases'], data['ladder_observations']
        self.assertEqual(len({c['id'] for c in cases}), 80)
        self.assertEqual(len({(o['id'], o['arm'], o['round']) for o in observations}), len(observations))
        for stratum, arms in data['ladder']['main_table'].items():
            ids = {c['id'] for c in cases if stratum == 'all' or c['stratum'] == stratum}
            for arm, reported in arms.items():
                successes = {o['id'] for o in observations if o['id'] in ids and o['arm'] == arm and o['metrics']['success']}
                cell = reported['success@3']
                self.assertEqual((cell['k'], cell['n']), (len(successes), len(ids)))
                self.assertEqual(cell['exact_ci95'], exact_binomial_interval(len(successes), len(ids)))
                for rnd, metrics in reported['rounds'].items():
                    rows = [o for o in observations if o['id'] in ids and o['arm'] == arm and o['round'] == int(rnd)]
                    self.assertEqual(metrics['observed_n'], len(rows))
                    for field in ('compliance', 'damage'):
                        values = [o['metrics'][field] for o in rows if o['metrics'][field] is not None]
                        self.assertEqual((metrics[field]['k'], metrics[field]['n']), (sum(values), len(values)))

    def test_public_paper_sampling_and_discard_replay_from_derived_outcomes(self):
        from replay import read, exact_binomial_interval
        data = read(study.ROOT / 'research/artifacts/decision-contract-20261022/results.json')
        c = data['consistency']
        self.assertEqual(c['majority_success']['k'], sum(r['selected_success'] for r in c['rows']))
        for stratum, reported in c['conditional_errors'].items():
            rows = [r for r in c['rows'] if r['stratum'] == stratum]
            self.assertEqual((reported['wrong']['k'], reported['wrong']['n']),
                             (sum(not r['selected_success'] for r in rows), len(rows)))
        m = data['metamorphic']
        self.assertEqual(len({(r['id'], r['kind']) for r in m['rows']}), 900)
        for kind, reported in m['by_transformation'].items():
            valid = [r for r in m['rows'] if r['kind'] == kind and r['valid']]
            flags = [r for r in valid if r['violation']]
            for name, values in [('violation', [r['violation'] for r in valid]),
                                 ('reference_false_positive', [r['false_alarm'] for r in flags])]:
                self.assertEqual((reported[name]['k'], reported[name]['n']), (sum(values), len(values)))
                self.assertEqual(reported[name]['exact_ci95'], exact_binomial_interval(sum(values), len(values)))
        flags = [r for r in m['rows'] if r['violation']]
        false = sum(r['false_alarm'] for r in flags)
        self.assertEqual((m['reference_false_positive']['k'], m['reference_false_positive']['n']), (false, len(flags)))
        self.assertEqual(m['discard_module'], false * 100 > len(flags) * data['design']['discard_threshold_percent'])
        self.assertIsNone(m['human_false_positive'])

    def test_ratio_rewrite_preserves_exact_values_and_excludes_ambiguous_multipliers(self):
        from decision_interventions import explicit_ratio_rewrite
        sample = case()
        sample['text'] = 'Use at least 25% of apples, twice the pears, and one third of the total.'
        result = explicit_ratio_rewrite(sample)
        self.assertEqual([e['value'] for e in result['edits']], ['1/4', '2', '1/3'])
        self.assertEqual(result['public_problem']['text'],
                         'Use at least (1/4 as a proportion) of apples, 200% of the pears, and (100/3)% of the total.')
        self.assertEqual(result['coordinate_map']['scales'], ['1', '1'])
        self.assertIsNone(result['human_meaning_preserved'])
        self.assertNotIn('PRIVATE_REFERENCE_SENTINEL', json.dumps(result))
        for text in ('Use twice more apples.', 'Take the third of these alternatives.', 'Use 10 units.'):
            sample['text'] = text
            with self.assertRaises(ValueError): explicit_ratio_rewrite(sample)

    def test_reference_metamorphic_false_alarm_can_mean_base_was_wrong(self):
        from decision_interventions import metamorphic_check, coordinate_transform
        from decision_geometry import compare_models
        wrong = deepcopy(BOX)
        wrong['constraints'][0]['b'] = '1'
        mapping = {'scales': ['10', '10'], 'permutation': [0, 1]}
        correct_transformed = coordinate_transform(BOX, **mapping)
        check = metamorphic_check(wrong, correct_transformed, mapping)
        self.assertTrue(check['violation'])
        self.assertTrue(compare_models(coordinate_transform(BOX, **mapping), correct_transformed)['equivalent'])
        self.assertFalse(metamorphic_check(BOX, correct_transformed, mapping)['violation'])

    def test_official_encoding_extension_retains_known_fraction_and_sum_meanings(self):
        from decision_ladder import expanded_official_record
        raw = {'vars': ['A', 'B'], 'var_mention_to_first_var': {},
               'obj_declaration': {'type': 'objvar', 'direction': 'minimum', 'vars': ['A', 'B']},
               'const_declarations': [{'type': 'xby', 'x_var': 'A', 'y_var': 'B', 'param': 'three times', 'operator': 'GREATER_OR_EQUAL'},
                                      {'type': 'sum', 'limit': 'twenty', 'operator': 'LESS_OR_EQUAL'}]}
        result = expanded_official_record('synthetic', raw)
        self.assertEqual(result['objective'], ['1', '1'])
        self.assertEqual(result['constraints'][0]['a'], ['1', '-3'])
        self.assertEqual(result['constraints'][1]['b'], '20')
        self.assertNotIn('terms', raw['obj_declaration'])
        raw['const_declarations'][0]['param'] = 'maybe three'
        with self.assertRaises(ValueError): expanded_official_record('synthetic', raw)

    def test_missing_anchor_is_explicit_and_not_claimed_as_exposed(self):
        from decision_interventions import ladder_request
        peer = deepcopy(BOX)
        peer['constraints'][0]['b'] = 1
        result = ladder_request(case(), BOX, peer, 'point+anchor', 1, allow_missing_anchor=True)
        payload = json.loads(result['request']['messages'][1]['content'])
        self.assertIsNone(payload['source_anchor'])
        self.assertFalse(result['scoring_context']['anchor_exposed'])

    def test_metamorphic_statistics_do_not_count_three_transforms_as_three_problems(self):
        from replay import summarize_metamorphic
        ids = [str(i) for i in range(300)]
        observations = [{"case_id": i, "kind": kind, "valid_pair": True, "violation": i == "0"}
                        for i in ids for kind in ("unit_scale", "variable_rename", "percent_ratio")]
        result = summarize_metamorphic(ids, observations, [])
        self.assertEqual(result["any_violation_complete_problem"]["n"], 300)
        self.assertEqual(result["any_violation_complete_problem"]["k"], 1)
        self.assertEqual(result["human_false_positive"]["flagged_n"], 3)
        self.assertIsNone(result["human_false_positive"]["false_positive_rate"])
        observations[-1].update(valid_pair=False, violation=None)
        result = summarize_metamorphic(ids, observations, [])
        self.assertEqual(result["any_violation_complete_problem"]["n"], 299)
        self.assertEqual(result["by_transformation"]["percent_ratio"]["invalid_n"], 1)
        with self.assertRaises(ValueError):
            summarize_metamorphic(ids[:-1], observations, [])

    def test_ladder_matched_feedback_does_not_leak_gold_or_fabricate_anchors(self):
        from decision_interventions import ladder_request
        c = case()
        peer = deepcopy(BOX)
        peer["constraints"][0]["b"] = 1
        verdict = ladder_request(c, BOX, peer, "verdict", 1)
        point = ladder_request(c, BOX, peer, "point", 1)
        v = json.loads(verdict["request"]["messages"][1]["content"])
        p = json.loads(point["request"]["messages"][1]["content"])
        witness = p.pop("previous_witness")
        self.assertEqual(v, p)
        self.assertNotIn("SENTINEL", json.dumps(point))
        self.assertFalse(verdict["scoring_context"]["witness_exposed"])
        with self.assertRaises(ValueError):
            ladder_request(c, BOX, peer, "point+anchor", 1)
        anchor = {"start": 0, "end": len(c["text"]), "text": c["text"], "row": witness["target_row"]}
        anchored = ladder_request(c, BOX, peer, "point+anchor", 1, anchor)
        a = json.loads(anchored["request"]["messages"][1]["content"])
        a.pop("source_anchor")
        self.assertEqual(a, json.loads(point["request"]["messages"][1]["content"]))
        no_witness = ladder_request(c, peer, peer, "point+anchor", 1)
        self.assertFalse(no_witness["scoring_context"]["anchor_exposed"])

    def test_ladder_denominator_is_eighty_not_number_of_rounds(self):
        from replay import summarize_ladder
        changed = deepcopy(BOX)
        changed["constraints"][0]["b"] = 1
        cases = [{"id": str(i), "text": f"Synthetic question {i}", "reference": BOX,
                  "stratum_protocol": "synthetic_two_draw", "stratum": "divergent" if i < 60 else "all_consistent_wrong",
                  "screening_models": [BOX, changed] if i < 60 else [changed, changed]} for i in range(80)]
        observations = [{"id": str(i), "arm": arm, "round": 1,
                         "metrics": {"success": True, "valid": True, "compliance": None, "damage": False}}
                        for i in range(80) for arm in ("verdict", "point", "point+anchor")]
        result = summarize_ladder(cases, observations)
        self.assertEqual(result["status"], "complete")
        cell = result["main_table"]["all"]["point"]
        self.assertEqual(cell["success@3"]["n"], 80)
        self.assertEqual(cell["success@3"]["k"], 80)
        self.assertEqual(cell["rounds"]["1"]["compliance"]["n"], 0)
        self.assertIsNone(cell["rounds"]["1"]["compliance"]["exact_ci95"])
        self.assertEqual(result["MDE"]["all"]["approximate_pp"], 15)
        observations.pop()
        missing = summarize_ladder(cases, observations)
        self.assertEqual(missing["status"], "incomplete")
        self.assertEqual(missing["main_table"]["all"]["point+anchor"]["success@3"]["k"], 79)

    def test_transform_review_packages_are_blind_pending_and_never_overwritten(self):
        import decision_annotation as annotations
        source = self.out / "source"
        raw_path = source / "source-snapshot/datasets/llm-grounding-v1/nl4opt-test.jsonl"
        raw_path.parent.mkdir(parents=True)
        record = {"document": "apples are 25% of fruit and pears are the rest.", "vars": ["apples", "pears"],
                  "var_mention_to_first_var": {"apples": "apples", "pears": "pears"},
                  "spans": [{"start": 0, "end": 6, "label": "VAR"}, {"start": 28, "end": 33, "label": "VAR"}],
                  "reference": "PRIVATE_REFERENCE_SENTINEL"}
        raw_path.write_text(json.dumps({"1": record})+'\n', 'utf-8')
        (self.out / "prereg.json").write_text(json.dumps({"stages": {"T11": {"human_review_input_ids": ["1"]}}}), 'utf-8')
        with patch.object(annotations, 'select_cases', return_value=(["1"], [], set())):
            result = annotations.package_transform_reviews(source, self.out)
            self.assertFalse(result["experiment_complete"])
            self.assertEqual(result["prepared_transformations"], 3)
            for name in ("annotator_1", "annotator_2"):
                directory = self.out / "T11-review" / name
                self.assertNotIn("SENTINEL", (directory / "problems.json").read_text('utf-8'))
                returned = json.loads((directory / "annotations.json").read_text('utf-8'))
                self.assertTrue(all(r["meaning_preserved"] is None for r in returned["annotations"]))
            with self.assertRaises(ValueError):
                annotations.package_transform_reviews(source, self.out)

    def test_round_compliance_distinguishes_acceptance_from_correct_rejection(self):
        from decision_interventions import round_metrics
        wrong = deepcopy(BOX)
        wrong["constraints"][0]["b"] = "4"
        result = round_metrics(BOX, wrong, BOX, [3, 0])
        self.assertFalse(result["compliance"])
        self.assertTrue(result["point_membership_correct"])
        self.assertTrue(result["success"])
        self.assertFalse(result["damage"])
        self.assertEqual(result["protected_rows"], [1])

    def test_round_damage_detects_lost_rows_on_unbounded_rays(self):
        from decision_interventions import round_metrics
        opened = deepcopy(BOX)
        opened["constraints"] = [opened["constraints"][1]]
        result = round_metrics(BOX, BOX, opened, [1, 1])
        self.assertTrue(result["compliance"])
        self.assertTrue(result["damage"])
        self.assertEqual(result["damaged_rows"], [0])
        self.assertFalse(result["success"])

    def test_round_missing_invalid_and_empty_are_not_zero_damage(self):
        from decision_interventions import round_metrics
        result = round_metrics(BOX, BOX, BOX)
        self.assertIsNone(result["compliance"])
        self.assertEqual(result["compliance_reason"], "no_previous_witness")
        for after in (None, {}, {**BOX, "constraints": [{"a": [1, 0], "op": "<=", "b": -1}]}):
            with self.subTest(after=after):
                measured = round_metrics(BOX, BOX, after, [1, 1])
                self.assertFalse(measured["success"])
                self.assertIsNone(measured["damage"])

    def test_row_retention_checks_equality_and_lower_bounds(self):
        from decision_interventions import row_is_implied
        segment = {**BOX, "constraints": [{"a": [1, 1], "op": "=", "b": 2}]}
        self.assertTrue(row_is_implied(segment, {"a": [2, 2], "op": "=", "b": 4}))
        self.assertTrue(row_is_implied(segment, {"a": [1, 1], "op": ">=", "b": 2}))
        self.assertFalse(row_is_implied(segment, {"a": [1, 1], "op": "<=", "b": 1}))

    def test_coordinate_units_and_permutation_round_trip_exactly(self):
        from decision_interventions import coordinate_transform, metamorphic_check
        from decision_geometry import compare_models
        scaled = coordinate_transform(BOX, ["2", "3"], [1, 0])
        self.assertEqual(scaled["objective"], ["3", "2"])
        restored = coordinate_transform(scaled, ["1/3", "1/2"], [1, 0])
        self.assertTrue(compare_models(BOX, restored)["equivalent"])
        mapping = {"scales": ["2", "3"], "permutation": [1, 0]}
        self.assertFalse(metamorphic_check(BOX, scaled, mapping)["violation"])
        self.assertTrue(metamorphic_check(BOX, BOX, mapping)["violation"])
        self.assertIsNone(metamorphic_check(BOX, {}, mapping)["violation"])
        for scales, permutation in (([0, 1], [0, 1]), ([-1, 1], [0, 1]), ([1, 1], [0, 0]), ([1, 1], [False, True])):
            with self.assertRaises(ValueError):
                coordinate_transform(BOX, scales, permutation)

    def test_transformations_keep_private_references_out_and_wait_for_humans(self):
        from decision_interventions import transform_problem
        c = case()
        c["text"] = "apples must be 25% of all fruit; pears use 50 liters."
        transformed = transform_problem(c, "percent_ratio")
        self.assertIn("1/4 of", transformed["public_problem"]["text"])
        self.assertIn("50 liters", transformed["public_problem"]["text"])
        self.assertNotIn("SENTINEL", json.dumps(transformed))
        self.assertIsNone(transformed["human_meaning_preserved"])
        scaled = transform_problem(c, "unit_scale", scale="5/2")
        self.assertEqual(scaled["coordinate_map"]["scales"], ["5/2", "5/2"])
        c["text"] = "apples and pears"
        renamed = transform_problem(c, "variable_rename", rename_spans=[
            {"start": 0, "end": 6, "text": "apples", "variable_index": 0},
            {"start": 11, "end": 16, "text": "pears", "variable_index": 1}])
        self.assertEqual(renamed["public_problem"]["text"], "item A and item B")
        with self.assertRaises(ValueError):
            transform_problem(c, "percent_ratio")

    def test_span_mismatch_and_overlapping_rewrites_are_rejected(self):
        from decision_interventions import source_span, replace_spans
        with self.assertRaises(ValueError):
            source_span("abc", {"start": 0, "end": 2, "text": "bc"})
        with self.assertRaises(ValueError):
            replace_spans("abcd", [{"start": 0, "end": 2, "text": "ab", "replacement": "x"},
                                   {"start": 1, "end": 3, "text": "bc", "replacement": "y"}])

    def test_false_positive_threshold_is_strict_and_missing_reviews_stay_pending(self):
        from decision_interventions import false_positive_decision
        ids = [str(i) for i in range(20)]
        reviews = [{"id": i, "is_false_positive": i == "0", "reviewer_id": "synthetic_test_only", "reason": "test fixture"} for i in ids]
        self.assertEqual(false_positive_decision(ids, reviews)["status"], "accepted")
        reviews[1]["is_false_positive"] = True
        self.assertEqual(false_positive_decision(ids, reviews)["status"], "discarded")
        pending = false_positive_decision(ids, [])
        self.assertIsNone(pending["false_positive_rate"])
        self.assertEqual(pending["status"], "awaiting_human_review")
        reviews[0]["reviewer_id"] = ""
        with self.assertRaises(ValueError):
            false_positive_decision(ids, reviews)

    def test_ladder_refuses_duplicates_protocol_mixing_and_wrong_strata(self):
        from decision_interventions import validate_ladder_cohort
        changed = deepcopy(BOX)
        changed["constraints"][0]["b"] = 1
        cases = [{"id": str(i), "text": f"Unique synthetic problem {i}", "reference": BOX,
                  "stratum_protocol": "synthetic_two_draw", "stratum": "divergent" if i < 60 else "all_consistent_wrong",
                  "screening_models": [BOX, changed] if i < 60 else [changed, changed]} for i in range(80)]
        self.assertEqual(validate_ladder_cohort(cases), {"divergent": 60, "all_consistent_wrong": 20})
        for mutation in ("duplicate", "mixed", "quota", "correct_in_wrong"):
            sample = deepcopy(cases)
            if mutation == "duplicate": sample[1]["id"] = sample[0]["id"]
            if mutation == "mixed": sample[1]["stratum_protocol"] = "different"
            if mutation == "quota": sample[59]["stratum"] = "all_consistent_wrong"
            if mutation == "correct_in_wrong": sample[79]["screening_models"] = [BOX, BOX]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_ladder_cohort(sample)

    def setUp(self):
        # Use an explicitly writable project directory; the Windows sandbox's
        # redirected system temporary directory need not allow child writes.
        self.temp_root = Path(__file__).resolve().parents[1] / ".local/tests/decision-protocol"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.out = Path(self.temp.name)
        self.out_patch = patch.object(study, "OUT", self.out)
        self.out_patch.start()

    def tearDown(self):
        self.out_patch.stop()
        self.assertTrue(self.out.resolve().is_relative_to(self.temp_root.resolve()))
        self.temp.cleanup()

    def write_result(self, identifier, arm, payload, status="complete", raw=False):
        dest = self.out / "network" / (identifier + "_" + arm + ".result.json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({"status": status, "text": payload if raw else json.dumps(payload)}), "utf-8")

    def test_public_prompt_has_explicit_whitelist(self):
        c = case()
        public = study.public_prompt(c)
        self.assertEqual(set(public), {"public_problem", "variable_catalog", "task_scope"})
        self.assertEqual(public["variable_catalog"], {"x0": "apples", "x1": "pears"})
        before = deepcopy(public)
        c["reference"] = {"secret": "CHANGED_PRIVATE_REFERENCE"}
        self.assertEqual(study.public_prompt(c), before)
        self.assertNotIn("SENTINEL", json.dumps(study.request("test", public)))

    def test_initial_queues_do_not_depend_on_reference(self):
        c = case()
        with patch.object(study, "cases", return_value=[c]), contextlib.redirect_stdout(io.StringIO()):
            study.initial_queue("heldout")
        queue = study.read(self.out / "heldout-initial-queue.json")
        self.assertEqual(len(queue), 2)
        for request in queue:
            payload = json.loads(request["messages"][1]["content"])
            self.assertEqual(set(payload), {"public_problem", "variable_catalog", "task_scope", "instruction"})
            self.assertNotIn("SENTINEL", json.dumps(request))

    def test_repair_arms_share_all_inputs_except_witness_payload(self):
        c = case()
        other = deepcopy(BOX)
        other["constraints"].append({"a": ["1", "1"], "op": "<=", "b": "4"})
        self.write_result(c["id"], "A", BOX)
        self.write_result(c["id"], "B", other)
        with patch.object(study, "cases", return_value=[c]), contextlib.redirect_stdout(io.StringIO()):
            study.repair_queue("heldout")
        queue = study.read(self.out / "heldout-repair-queue.json")
        by_arm = {r["id"].rsplit("_", 1)[1]: r for r in queue}
        a = json.loads(by_arm["abstract"]["messages"][1]["content"])
        w = json.loads(by_arm["witness"]["messages"][1]["content"])
        self.assertEqual(by_arm["abstract"]["maxTokens"], by_arm["witness"]["maxTokens"])
        self.assertEqual(by_arm["abstract"]["messages"][0], by_arm["witness"]["messages"][0])
        self.assertTrue(w.pop("exact_concrete_witnesses"))
        w.pop("witness_note")
        self.assertEqual(a, w)
        self.assertFalse(a["exact_relation_diagnostics"]["feasible_sets_equal"])
        self.assertNotIn("SENTINEL", json.dumps(queue))

    def test_agreement_and_invalid_candidates_have_no_fabricated_witness(self):
        same = case("732")
        broken = case("733")
        for arm in ("A", "B"):
            self.write_result(same["id"], arm, BOX)
        self.write_result(broken["id"], "A", "not JSON", raw=True)
        self.write_result(broken["id"], "B", BOX)
        with patch.object(study, "cases", return_value=[same, broken]), contextlib.redirect_stdout(io.StringIO()):
            study.repair_queue("heldout")
        for row in study.read(self.out / "heldout-diagnostics.json"):
            self.assertEqual(row["witnesses"], [])
        bad = study.read(self.out / "heldout-diagnostics.json")[1]
        self.assertEqual(bad["verdict"]["status"], "candidate_parse_failure")

    def test_invalid_and_incomplete_outputs_are_rejected(self):
        invalid = [{}, [], None, {**BOX, "sense": "maximize"}, {**BOX, "objective": [1, float("nan")]},
                   {**BOX, "objective": [1]}, {**BOX, "objective": [True, 1]},
                   {**BOX, "constraints": [{"a": [1, 0], "op": "<", "b": 1}]},
                   {**BOX, "constraints": [{"a": [1, 0], "op": "<=", "b": "1/0"}]}]
        for value in invalid:
            with self.subTest(value=value):
                self.write_result("731", "A", value)
                self.assertFalse(study.candidate(case(), "A")["valid"])
        self.write_result("731", "A", BOX, status="length")
        self.assertFalse(study.candidate(case(), "A")["valid"])
        self.assertFalse(study.candidate(case(), "missing")["valid"])

    def test_unsupported_semantics_not_silently_discarded(self):
        for field, value in (("integrality", [1, 1]), ("objective_offset", 7), ("variables", {"x0": "integer"})):
            with self.subTest(field=field):
                self.write_result("731", "A", {**BOX, field: value})
                self.assertFalse(study.candidate(case(), "A")["valid"])
        badrow = deepcopy(BOX)
        badrow["constraints"][0]["strict"] = True
        self.write_result("731", "A", badrow)
        self.assertFalse(study.candidate(case(), "A")["valid"])

    def test_known_scoring_contract_separates_value_region_face_and_order(self):
        cases = [case(str(740 + i)) for i in range(4)]
        # Equal value/optimal point but a smaller feasible region must fail.
        smaller = deepcopy(BOX)
        smaller["constraints"].append({"a": [1, 1], "op": "<=", "b": 4})
        # Same feasible region/value but a larger optimal face must fail.
        face = {**BOX, "objective": [1, 0]}
        # Same feasible region/optimal point, different full objective order:
        # current-instance primary passes, separate order flag must fail.
        order = {**BOX, "objective": [2, 1]}
        predictions = [smaller, face, order, {}]
        for c, prediction in zip(cases, predictions):
            for arm in ("A", "B", "abstract", "witness"):
                self.write_result(c["id"], arm, prediction if arm != "witness" else BOX)
        with patch.object(study, "cases", return_value=cases), contextlib.redirect_stdout(io.StringIO()):
            study.evaluate("heldout")
        rows = study.read(self.out / "heldout-scores.json")
        self.assertEqual([r["arms"]["abstract"]["success"] for r in rows], [False, False, True, False])
        self.assertFalse(rows[2]["arms"]["abstract"]["comparison"]["objective_order_equal"])
        self.assertEqual([r["arms"]["witness"]["success"] for r in rows], [True] * 4)
        summary = study.read(self.out / "heldout-summary.json")
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["primary"]["gains"], 3)
        self.assertEqual(summary["primary"]["losses"], 0)
        self.assertEqual(summary["primary"]["pExact"], .25)
        self.assertFalse(summary["positiveGate"])

    def test_exact_paired_test_known_answers(self):
        r = study.mcnemar([False] * 6, [True] * 6)
        self.assertEqual(r["pExact"], .03125)
        self.assertEqual(r["difference"], 1)
        self.assertEqual(r["pairedBootstrap95"], [1, 1])
        r = study.mcnemar([False, True], [True, False])
        self.assertEqual(r["pExact"], 1)
        self.assertEqual(r["difference"], 0)


class OfflineReplayTests(unittest.TestCase):
    def test_consistency_clusters_keep_shared_errors_ties_and_failed_draws(self):
        import replay
        root = study.ROOT / ".local/tests/decision-protocol"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            output = Path(temporary)
            replay.save(output / "prereg.json", {"budget": {"max_model_calls": 18}, "reference_policy": "test gold", "conditioning": "six valid"})
            replay.save(output / "budget-spend.json", {"measured_usage_cost_CNY": 0})
            cases = [{"id": str(i), "reference": BOX} for i in range(3)]
            replay.save(output / "cases.private.json", cases)
            wrong = deepcopy(BOX)
            wrong["constraints"][0]["b"] = "1"
            for c in cases:
                for j in range(6):
                    model = wrong if c["id"] == "0" or j%2 == 0 else BOX
                    replay.save(output / "network" / f'{c["id"]}_s{j}.result.json',
                                {"status": "failed" if c["id"] == "2" else "complete", "text": json.dumps(model)})
            result = replay.score_consistency(output=output)
            self.assertEqual(result["strata"]["all_consistent"]["k"], 1)
            self.assertEqual(result["strata"]["divergent"]["k"], 1)
            self.assertEqual(result["strata"]["incomplete"]["n"], 1)
            saved = replay.read(output / "consistency.json")
            self.assertEqual(saved["rows"][1]["clusters"], [[0, 2, 4], [1, 3, 5]])
            self.assertEqual(saved["rows"][2]["clusters"], [])
            self.assertEqual(saved["conditional_errors"]["incomplete"]["by_error_type"]["invalid"]["k"], 1)
            self.assertEqual(saved["majority_success"]["n"], 3)
            self.assertAlmostEqual(saved["modal_share"]["mean"], .5)

    def test_frozen_verifier_detects_changed_bytes_and_checks_recorded_moves(self):
        import hashlib
        import zipfile
        import replay
        root = study.ROOT / ".local/tests/decision-protocol"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            project = Path(temporary)
            source = project / "frozen"
            source.mkdir()
            request = {"messages": [{"role": "user", "content": "synthetic fixture"}]}
            replay.save(source / "network/call.request.json", request)
            replay.save(source / "network/call.result.json", {"status": "complete"})
            events = [{"event": "started", "id": "call", "sequence": 1,
                       "promptSha256": hashlib.sha256(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()},
                      {"event": "finished", "id": "call", "status": "complete"}]
            (source / "calls.jsonl").write_text("\n".join(map(json.dumps, events)), "utf-8")
            replay.save(source / "heldout-scores.json", [])
            replay.save(source / "protocol.json", {"budget": {"totalAuthorizedRequests": 1}, "sourceHashes": {}})
            replay.save(source / "amendment-001-parser-validation.json", {"changed": {}})
            (source / "notes.txt").write_text("original prose", "utf-8")
            files = replay.inventory(source)
            replay.save(source / "manifest.json", {"files": [{"path": k, **v} for k, v in files.items()]})
            with zipfile.ZipFile(source / "证据包.zip", "w") as archive:
                for name in list(files)+["manifest.json"]:
                    archive.write(source / name, name)
            replay.save(source / "seal-result.json", {"zipSha256": replay.sha(source / "证据包.zip")})
            self.assertTrue(replay.freeze_check(source, project)[0]["passed"])
            moved = project / "_归档_自我否定/frozen/notes.txt"
            moved.parent.mkdir(parents=True)
            (source / "notes.txt").rename(moved)
            self.assertFalse(replay.freeze_check(source, project)[0]["passed"])
            replay.save(project / "_归档_自我否定/cleanup.json", {"moved": ["frozen/notes.txt"]})
            self.assertTrue(replay.freeze_check(source, project)[0]["passed"])
            moved.write_text("altered prose", "utf-8")
            self.assertFalse(replay.freeze_check(source, project)[0]["passed"])
            moved.write_text("original prose", "utf-8")
            replay.save(source / "heldout-scores.json", ["tampered"])
            report = replay.freeze_check(source, project)[0]
            self.assertFalse(report["passed"])
            self.assertIn("key_file_hash_mismatch", [x["kind"] for x in report["discrepancies"]])

    def test_table_replay_rejects_changed_cells_without_rewriting_evidence(self):
        import replay
        root = study.ROOT / ".local/tests/decision-protocol"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            output = Path(temporary) / "output"
            source = Path(temporary) / "source"
            source.mkdir()
            stats = {"correct": 1, "n": 2, "rate": .5, "exact_ci95": [.1, .9], "rank": 1}
            result = {"frozen_summary": {a: stats for a in replay.ARMS}, "variants": {}, "replayed_raw_responses": 8}
            baseline = {"n": 2, "methods": {a: stats for a in ("pick-A", "pick-B", "oracle-select")}}
            frozen = {"passed": True, "anchors": {"test": "hash"}}
            for name, data in {"freeze-check.json": frozen, "gold_overrides.json": {}, "admissible_readings.json": {},
                               "rescore.json": result, "baselines.json": baseline}.items():
                replay.save(output / name, data)
            (output / "manifest.tsv").write_text("path\tbytes\tsha256\n", "utf-8")
            with patch.object(replay, "paper_facts", return_value="facts\n"):
                replay.write_tables(source, output)
                table_path = output / "tables.json"
                corrupt = replay.read(table_path)
                corrupt["table1"][0]["correct"] = 999
                replay.save(table_path, corrupt)
                tex = output / "paper/tables.tex"
                tex.write_text(tex.read_text("utf-8")+"% changed\n", "utf-8")
                before = {p: p.read_bytes() for p in output.rglob("*") if p.is_file()}
                with patch.object(replay, "freeze_check", return_value=(frozen, {})), \
                     patch.object(replay, "make_readings", return_value=({}, {})), \
                     patch.object(replay, "rescore", return_value=result) as raw_replay, \
                     patch.object(replay, "baselines", return_value=baseline):
                    report = replay.check_replay(source, output)
                raw_replay.assert_called_once_with(source.resolve(), {})
                self.assertFalse(report["passed"])
                self.assertEqual(report["differences"], ["tables.json", "paper/tables.tex"])
                self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))

    def test_binomial_interval_endpoints_and_symmetry(self):
        from replay import exact_binomial_interval
        self.assertAlmostEqual(exact_binomial_interval(0, 10)[1], 1 - .025 ** .1)
        self.assertAlmostEqual(exact_binomial_interval(10, 10)[0], .025 ** .1)
        self.assertEqual(exact_binomial_interval(0, 1)[0], 0)
        for k in range(11):
            left = exact_binomial_interval(k, 10)
            right = exact_binomial_interval(10-k, 10)
            self.assertAlmostEqual(left[0], 1-right[1])
            self.assertLessEqual(left[0], k/10)
            self.assertGreaterEqual(left[1], k/10)

    def test_exact_counterexample_and_feasible_witness_have_distinct_roles(self):
        from replay import memberships
        model = {"constraints": [{"a": ["-1", "3"], "op": ">=", "b": "0"}]}
        self.assertFalse(memberships(model, ["4", "1"]))
        self.assertTrue(memberships(model, ["3", "1"]))
        self.assertFalse(memberships(model, ["-1", "1"]))

    def test_evidence_path_cannot_escape_root(self):
        from replay import safe_member
        with self.assertRaises(ValueError):
            safe_member(Path.cwd(), "../outside")

    def test_frozen_output_directory_is_rejected_before_writing(self):
        from replay import write_freeze
        with self.assertRaises(ValueError):
            write_freeze(Path.cwd(), Path.cwd() / "new-output")

    def test_admissible_scoring_does_not_accept_known_erroneous_official_reading(self):
        from replay import make_readings, SOURCE
        if not (SOURCE / "annotation-review.json").is_file():
            self.skipTest("Local frozen evidence is not part of the public checkout")
        from decision_geometry import compare_models
        overrides, readings = make_readings()
        self.assertEqual(len(overrides["entries"]), 7)
        self.assertEqual(readings["variants"]["seven_case"], readings["variants"]["seven_plus_all_annotation"])
        case = next(e for e in overrides["entries"] if e["id"] == "-272035411")
        official = {"sense": case["sense"], "objective": case["objective"], "constraints": case["official_rows"]}
        accepted = readings["variants"]["seven_case"][case["id"]]
        self.assertEqual(len(accepted), 1)
        self.assertFalse(compare_models(official, accepted[0])["feasible_sets_equal"])

    def test_nominal_alpha_known_answers_and_missing_labels(self):
        from decision_annotation import nominal_alpha
        self.assertIsNone(nominal_alpha([(None, None)])["alpha"])
        self.assertIsNone(nominal_alpha([("unique", "unique")]*4)["alpha"])
        self.assertEqual(nominal_alpha([("unique", "unique"), ("ambiguous", "ambiguous")])["alpha"], 1)
        pairs = [("unique", "unique"), ("unique", "ambiguous"), ("ambiguous", "ambiguous"), ("ambiguous", "ambiguous")]
        self.assertAlmostEqual(nominal_alpha(pairs)["alpha"], 8/15)
        self.assertAlmostEqual(nominal_alpha(pairs+[(None, "unique")])["alpha"], 8/15)

    def test_annotation_agreement_rejects_same_annotator_and_duplicate_ids(self):
        from decision_annotation import agreement
        row = {"id": "1", "reading_status": None, "models": [], "notes": ""}
        a = {"annotator_id": "a", "annotations": [row]}
        with self.assertRaises(ValueError):
            agreement(a, a)
        with self.assertRaises(ValueError):
            agreement(a, {"annotator_id": "b", "annotations": [row, row]})


if __name__ == "__main__":
    unittest.main()
