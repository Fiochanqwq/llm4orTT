"""T11 existing-data transformations and reference-conditional alarm evaluation."""
from __future__ import annotations
import argparse
import hashlib
from fractions import Fraction as F
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay import ROOT, read, save, load_candidate, exact_binomial_interval, sha
from decision_contract_study import public_prompt, request
from decision_geometry import compare_models
from decision_interventions import transform_problem, explicit_ratio_rewrite, coordinate_transform, metamorphic_check, source_span
from decision_ladder import register_queue, source_records

KINDS = ['unit_scale', 'variable_rename', 'percent_ratio']


def prepare_candidates(batch):
    pool = read(batch / 'T8-screening-expanded/cases.private.json')
    raw = source_records(batch)
    candidates, exclusions = [], []
    for case in pool:
        try:
            original = load_candidate(ROOT / case['initial_source'], case, 'A')
            if not original['valid']: raise ValueError('Existing base A output is invalid')
            record = raw[case['id']]
            spans = []
            for span in record.get('spans', []):
                if span.get('label') != 'VAR': continue
                mention = span.get('text', case['text'][span['start']:span['end']])
                checked = source_span(case['text'], {'start': span['start'], 'end': span['end'], 'text': mention})
                canonical = record['var_mention_to_first_var'].get(mention, mention)
                if canonical not in case['variables']: raise ValueError('Unmapped variable mention')
                spans.append({**checked, 'variable_index': case['variables'].index(canonical)})
            transforms = [transform_problem(case, 'unit_scale', scale=10),
                          transform_problem(case, 'variable_rename', rename_spans=spans), explicit_ratio_rewrite(case)]
            candidates.append({**case, 'base_model': original['model'], 'transformations': transforms})
        except (ValueError, KeyError) as exc:
            exclusions.append({'id': case['id'], 'reason': str(exc)})
    save(batch / 'T11-input-coverage.json', {'pool_n': len(pool), 'supported_complete_triplet_n': len(candidates),
         'required_n': 300, 'excluded': exclusions, 'status': 'ready' if len(candidates) >= 300 else 'insufficient_complete_triplets'})
    return candidates


def prepare(batch):
    candidates = prepare_candidates(batch)
    if len(candidates) < 300:
        return {'ready': False, 'complete_triplets': len(candidates), 'required': 300, 'new_model_calls': 0}
    selected = sorted(candidates, key=lambda c: hashlib.sha256(('T11-20261022:'+c['id']).encode()).hexdigest())[:300]
    queue = []
    for case in selected:
        for transform in case['transformations']:
            prompt = public_prompt(transform['public_problem'])
            prompt['instruction'] = 'Construct the complete LP directly from the original description.'
            queue.append(request(case['id']+'_'+transform['kind'], prompt))
    random.Random(2026102211).shuffle(queue)
    prior = [ROOT / '实验/任务板执行_2026-10-22_02/budget-spend.json', batch / 'harness-spend.json',
             batch / 'T8-screening/budget-spend.json', batch / 'T8-screening-expanded/budget-spend.json']
    prior += [batch / f'T8-round-{r}/budget-spend.json' for r in (1, 2, 3)]
    output = batch / 'T11'
    details = {'task': 'T11', 'phase': 'metamorphic', 'n': 300, 'MDE': None, 'arms': KINDS,
        'selection': 'First 300 supported distinct original problems by SHA256(T11-20261022:<id>), before new transformed outputs.',
        'base_policy': 'Reuse valid existing A outputs from screening, retaining original source split. No new baseline calls.',
        'transformation_policy': {'unit_scale': 'New variables count groups of ten original units; exact old x = 10 * new x.',
                                  'variable_rename': 'Replace all source-annotated VAR spans with item A/B; preserve variable ordering.',
                                  'percent_ratio': 'Rewrite dimensionless percentage literals into explicit fractions as proportions, or supported multipliers into percentages; exclude times-more phrases and unsupported text.'},
        'primary': 'Per-transformation equivariance violation rate among valid pairs, plus any violation per complete original problem.',
        'false_positive_target': 'An alarm accuses the transformed output of being wrong. False alarm = alarm AND transformed output is exactly equivalent to transformed official reference. The original output may be the erroneous side.',
        'reference_false_positive_denominator': 'All valid alarmed transformed outputs, checked exhaustively against mapped official reference. Not human-validated semantic false positives.',
        'discard_rule': 'Discard the module when the pooled reference-conditional false-alarm proportion exceeds 5%. Preserve all outputs and per-transformation counts.',
        'human_validation': 'None. Rule-based text transformations and exact reference maps are documented separately; AI consultation is not a ground-truth annotation.',
        'unknown_outputs': 'Failed or invalid outputs are recorded as failures with no equivariance verdict; no retries or replacement sample.'}
    prereg = register_queue(output, queue, details, prior, completion_tokens=120)
    save(output / 'cases.private.json', selected)
    return {'ready': True, 'n': len(selected), 'estimate': prereg['estimate']}


def cell(values):
    n, k = len(values), sum(values)
    return {'k': k, 'n': n, 'rate': k/n if n else None, 'exact_ci95': exact_binomial_interval(k, n) if n else None}


def score(batch):
    output = batch / 'T11'
    cases = read(output / 'cases.private.json')
    if len(cases) != 300 or len({c['id'] for c in cases}) != 300: raise ValueError('T11 cohort changed')
    rows = []
    for case in cases:
        for transform in case['transformations']:
            kind = transform['kind']
            candidate = load_candidate(output, case, kind)
            row = {'id': case['id'], 'kind': kind, 'source_split': case['source_split'], 'valid': candidate['valid'],
                   'violation': None, 'reference_correct': None, 'false_alarm': None}
            if candidate['valid']:
                result = metamorphic_check(case['base_model'], candidate['model'], transform['coordinate_map'])
                reference = coordinate_transform(case['reference'], **transform['coordinate_map'])
                correct = compare_models(reference, candidate['model'])['equivalent']
                row.update(violation=result['violation'], reference_correct=correct,
                           false_alarm=bool(result['violation'] and correct))
            else: row['error'] = candidate.get('error')
            rows.append(row)
    by_kind = {}
    for kind in KINDS:
        group = [r for r in rows if r['kind'] == kind]
        valid = [r for r in group if r['valid']]
        flags = [r for r in valid if r['violation']]
        by_kind[kind] = {'violation': cell([r['violation'] for r in valid]), 'reference_false_positive': cell([r['false_alarm'] for r in flags]),
                         'valid_n': len(valid), 'invalid_n': len(group)-len(valid), 'planned_n': 300}
    flags = [r for r in rows if r['violation']]
    k, n = sum(r['false_alarm'] for r in flags), len(flags)
    discard = bool(n and F(k, n) > F(1, 20))
    complete = [[r for r in rows if r['id'] == c['id']] for c in cases]
    complete = [group for group in complete if all(r['valid'] for r in group)]
    result = {'schema': 'metamorphic-reference-evaluation.v1', 'n': 300, 'rows': rows, 'by_transformation': by_kind,
              'any_violation_complete_problem': cell([any(r['violation'] for r in group) for group in complete]),
              'reference_false_positive': {'k': k, 'n': n, 'rate': k/n if n else None,
                 'denominator': 'All valid flagged transformed outputs; conditional on the published reference. Repeated transforms are not independent problems.'},
              'human_false_positive': None, 'discard_module': discard,
              'status': 'discarded' if discard else 'no_flags_to_estimate_false_positive' if not n else 'completed_reference_conditioned',
              'budget': read(output / 'budget-spend.json'), 'prereg_sha256': sha(output / 'prereg.json')}
    save(output / 'metamorphic.json', result)
    return {k: result[k] for k in ('n', 'by_transformation', 'reference_false_positive', 'discard_module', 'status')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('coverage', 'prepare', 'score'))
    parser.add_argument('--batch', type=Path, required=True)
    args = parser.parse_args()
    batch = args.batch.resolve()
    result = {'supported_complete_triplets': len(prepare_candidates(batch))} if args.action == 'coverage' else prepare(batch) if args.action == 'prepare' else score(batch)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
