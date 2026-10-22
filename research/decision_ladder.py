"""T8 preparation and repair scheduling, retaining source cohorts and failed attempts."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import sys
from copy import deepcopy
from fractions import Fraction as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay import ROOT, SOURCE, read, save, sha, load_candidate
from decision_contract_study import public_prompt, request, canonical_record
from decision_geometry import compare_models, analyze_model
from decision_interventions import validate_ladder_cohort, ladder_request, round_metrics

ARMS = ['verdict', 'point', 'point+anchor']
PRICES = {'peak': {'hit': .04, 'miss': 2, 'output': 8}, 'off_peak': {'hit': .02, 'miss': 1, 'output': 4}}


def register_queue(output, queue, details, prior_reports, completion_tokens=100):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT / '实验') or output.is_relative_to(SOURCE):
        raise ValueError('Use a fresh experiment subdirectory outside frozen data')
    if not queue:
        raise ValueError('No queue to dispatch')
    # UTF-8 bytes conservatively bound prompt tokens; output is an estimate,
    # while dispatch reserves the full max_tokens bound for each in-flight call.
    estimated_input = sum(len(json.dumps(q['messages'], ensure_ascii=False).encode())+256 for q in queue)
    costs = {}
    for period, prices in PRICES.items():
        costs[period] = {'input_CNY': estimated_input*prices['miss']/1e6,
                         'output_CNY': len(queue)*completion_tokens*prices['output']/1e6}
        costs[period]['total_CNY'] = sum(costs[period].values())
    reports = [{'path': Path(p).resolve().relative_to(ROOT).as_posix(), 'sha256': sha(p)} for p in prior_reports]
    budget = {'total_CNY': 15, 'stop_remaining_CNY': 3, 'max_model_calls': len(queue),
              'automatic_retries': 0, 'prior_spend_reports': reports}
    spent = sum(read(p).get('current_run_accounted_CNY', read(p)['accounted_upper_CNY']) for p in prior_reports)
    if spent + costs['peak']['total_CNY'] > 12:
        raise ValueError('Estimated queue would consume the registered budget floor')
    prereg = {'schema': 'task-board-paid.v2', 'task': 'T8', 'n': 80, 'MDE': {'approximate_pp': 15},
              'arms': ARMS, 'model': 'deepseek-flash', 'budget': budget,
              'estimate': {'calls': len(queue), 'input_token_upper': estimated_input, 'mean_output_estimate': completion_tokens,
                           'costs': costs},
              'switching_rules': ['Never retry a failed or attempted request.', 'Stop before consuming the twenty-percent budget floor.',
                                  'Do not shrink the 60+20 strata or mix screening protocols.',
                                  'Invalid results remain in the ledger and cannot be assigned an agreement stratum.'],
              **details}
    output.mkdir(parents=True)
    save(output / 'prereg.json', prereg)
    save(output / 'queue.json', queue)
    save(output / 'budget.json', {'schema': 'task-board-budget.v2', **budget, 'model': 'deepseek-flash', 'prices': PRICES,
                                 'queue_sha256': sha(output / 'queue.json'), 'prereg_sha256': sha(output / 'prereg.json')})
    (output / 'execution.log').write_text(f'预估调用数：{len(queue)}；预估费用：峰值 ¥{costs["peak"]["total_CNY"]:.6f}（输入 ¥{costs["peak"]["input_CNY"]:.6f}、输出 ¥{costs["peak"]["output_CNY"]:.6f}），谷值 ¥{costs["off_peak"]["total_CNY"]:.6f}；累计预算及停止线见 prereg.json。\n', 'utf-8')
    return prereg


def prepare_screening(batch):
    cases = read(batch / 'source-data/eligible.private.json')
    old = {c['id']: c for c in read(SOURCE / 'cases.private.json')}
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Source splits contain colliding IDs')
    queue, reused = [], []
    for c in cases:
        if c['source_split'] == 'test' and c['id'] in old:
            if c['text'] != old[c['id']]['text'] or c['reference'] != old[c['id']]['reference']:
                raise ValueError('Frozen case does not match source record')
            c['initial_source'] = SOURCE.relative_to(ROOT).as_posix()
            reused.append(c['id'])
            continue
        c['initial_source'] = (batch / 'T8-screening').resolve().relative_to(ROOT).as_posix()
        for arm in ('A', 'B'):
            prompt = public_prompt(c)
            prompt['instruction'] = ('Construct the complete LP directly from the original description.' if arm == 'A' else
                'Independently translate each stated requirement, checking ratios, units and direction. Build the complete LP without access to another formulation.')
            queue.append(request(c['id']+'_'+arm, prompt))
    random.Random(202610228).shuffle(queue)
    target = batch / 'T8-screening'
    prereg = register_queue(target, queue,
        {'phase': 'screening', 'screening_n': len(queue)//2, 'screening_arms': ['A', 'B'],
         'screening_pool_n': len(cases), 'reused_case_ids': reused,
         'selection': 'Exact A/B relation; retain all input results. For each target stratum take the first required IDs sorted by SHA256(T8-20261022:<id>).',
         'reference_policy': 'Official NL4Opt structured reference; known corrections remain sensitivity-only. All claims conditional on this reference.',
         'data_split_policy': 'Record test/train/dev provenance; training examples are not presented as an independent test set.',
         'source_manifest_sha256': sha(batch / 'source-data/manifest.json'),
         'pool_sha256': sha(batch / 'source-data/eligible.private.json')},
        [ROOT / '实验/任务板执行_2026-10-22_02/budget-spend.json', batch / 'harness-spend.json'])
    save(target / 'cases.private.json', cases)
    return prereg['estimate']


def expanded_official_record(identifier, raw):
    """Additional official encodings only; the original parser is left unchanged."""
    normalized = deepcopy(raw)
    directions = {'maximum': 'maximize', 'maximizing': 'maximize', 'highest': 'maximize', 'most': 'maximize',
                  'minimum': 'minimize', 'minimizing': 'minimize', 'minimizes': 'minimize',
                  'minimal': 'minimize', 'lowest': 'minimize', 'reduce': 'minimize'}
    obj = normalized['obj_declaration']
    direction = obj['direction'].lower().strip()
    obj['direction'] = directions.get(direction, direction)
    if obj.get('type') == 'objvar' and 'terms' not in obj:
        if not obj.get('vars') or len(set(obj['vars'])) != len(obj['vars']):
            raise ValueError('Invalid objective variable list')
        obj['terms'] = {name: '1' for name in obj['vars']}
    if not obj.get('terms'):
        raise ValueError('Empty objective coefficients')
    words = {w: str(i) for i, w in enumerate(('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty').split())}
    words.update({'thirty': '30', 'forty': '40', 'fifty': '50', 'sixty': '60', 'seventy': '70', 'eighty': '80', 'ninety': '90',
                  'half': '1/2', 'third': '1/3', 'quarter': '1/4', 'a third': '1/3', 'one third': '1/3',
                  'twice': '2', 'double': '2', 'thrice': '3', 'one hundred thousand': '100000'})
    def number(value):
        text = str(value).lower().strip().replace(',', '')
        percent = text.endswith('%') or text.endswith(' percent')
        if percent: text = text[:-1].strip() if text.endswith('%') else text[:-8].strip()
        text = re.sub(r'\s+times$', '', text)
        if re.fullmatch(r'\d+(?:\.\d+)?\$\.', text): text = text[:-2]
        value = F(words.get(text, text))
        return str(value/100 if percent else value)
    obj['terms'] = {name: number(value) for name, value in obj['terms'].items()}
    for row in normalized['const_declarations']:
        if 'terms' in row: row['terms'] = {name: number(v) for name, v in row['terms'].items()}
        for key in ('limit', 'param'):
            if key in row: row[key] = number(row[key])
    return canonical_record(identifier, normalized)


def prepare_expanded_screening(batch):
    prior = read(batch / 'T8-screening/cases.private.json')
    ids, texts = {c['id'] for c in prior}, {' '.join(c['text'].lower().split()) for c in prior}
    additions, rejected, queue = [], [], []
    output = batch / 'T8-screening-expanded'
    paths = [('test', ROOT / 'datasets/llm-grounding-v1/nl4opt-test.jsonl'),
             ('train', batch / 'source-data/train.jsonl'), ('dev', batch / 'source-data/dev.jsonl')]
    for split, path in paths:
        for line in path.read_text('utf-8-sig').splitlines():
            for identifier, raw in json.loads(line).items():
                if identifier in ids: continue
                try:
                    reference = expanded_official_record(identifier, raw)
                    if analyze_model(reference)['status'] != 'optimal': raise ValueError('No finite optimum')
                    text = ' '.join(raw['document'].lower().split())
                    if text in texts: raise ValueError('Duplicate source text')
                    texts.add(text); ids.add(identifier)
                    c = {'id': identifier, 'text': raw['document'], 'variables': raw['vars'], 'reference': reference,
                         'source_split': split, 'parser': 'official_encoding_extension_v1',
                         'initial_source': output.relative_to(ROOT).as_posix()}
                    additions.append(c)
                    for arm in ('A', 'B'):
                        payload = public_prompt(c)
                        payload['instruction'] = ('Construct the complete LP directly from the original description.' if arm == 'A' else
                            'Independently translate each stated requirement, checking ratios, units and direction. Build the complete LP without access to another formulation.')
                        queue.append(request(identifier+'_'+arm, payload))
                except (ValueError, KeyError) as exc:
                    rejected.append({'id': identifier, 'source_split': split, 'reason': str(exc)})
    random.Random(2026102281).shuffle(queue)
    details = {'phase': 'screening', 'screening_n': len(additions), 'screening_arms': ['A', 'B'],
               'screening_pool_n': len(prior)+len(additions), 'parser_sha256': sha(Path(__file__)),
               'amendment': 'After the complete initial pool yielded insufficient divergence, support explicit official objvar sums, objective-direction synonyms and numeric word encodings. No earlier answer or reference is changed; only previously excluded IDs are requested.',
               'selection': 'Same frozen_A_B_two_prompt_v1; SHA256(T8-20261022:<id>) within fixed 60+20 strata over the complete combined pool.',
               'reference_policy': 'Conditional on published structured answers; sensitivity policies remain separate.'}
    prereg = register_queue(output, queue, details, [ROOT / '实验/任务板执行_2026-10-22_02/budget-spend.json',
                             batch / 'harness-spend.json', batch / 'T8-screening/budget-spend.json'])
    save(output / 'cases.private.json', prior+additions)
    save(output / 'parser-exclusions.json', rejected)
    return {'added_problems': len(additions), 'estimate': prereg['estimate']}


def score_screening(batch):
    output = batch / ('T8-screening-expanded' if (batch / 'T8-screening-expanded/cases.private.json').exists() else 'T8-screening')
    cases = read(output / 'cases.private.json')
    strata = {'divergent': [], 'all_consistent_wrong': []}
    rows = []
    for c in cases:
        candidates = [load_candidate(ROOT / c['initial_source'], c, arm) for arm in ('A', 'B')]
        row = {'id': c['id'], 'source_split': c['source_split'], 'valid_pair': all(x['valid'] for x in candidates), 'stratum': None}
        if row['valid_pair']:
            models = [x['model'] for x in candidates]
            same = compare_models(*models)['equivalent']
            correct = [compare_models(c['reference'], m)['equivalent'] for m in models]
            row.update(agreement=same, correct=correct)
            row['stratum'] = 'divergent' if not same else 'all_consistent_wrong' if not correct[0] else 'all_consistent_correct'
            if row['stratum'] in strata:
                strata[row['stratum']].append({**c, 'stratum': row['stratum'], 'stratum_protocol': 'frozen_A_B_two_prompt_v1', 'screening_models': models})
        else:
            row['errors'] = [x.get('error') for x in candidates]
        rows.append(row)
    counts = {name: len(group) for name, group in strata.items()}
    eligible = counts['divergent'] >= 60 and counts['all_consistent_wrong'] >= 20
    save(output / 'screening.json', {'n': len(rows), 'rows': rows, 'counts': counts, 'target_ready': eligible})
    if eligible:
        selected = []
        for stratum, n in (('divergent', 60), ('all_consistent_wrong', 20)):
            selected += sorted(strata[stratum], key=lambda c: hashlib.sha256(('T8-20261022:'+c['id']).encode()).hexdigest())[:n]
        validate_ladder_cohort(selected)
        save(batch / 'T8-cases.private.json', selected)
    return {'counts': counts, 'target_ready': eligible}


def source_records(batch):
    result = {}
    for path in (ROOT / 'datasets/llm-grounding-v1/nl4opt-test.jsonl', batch / 'source-data/train.jsonl', batch / 'source-data/dev.jsonl'):
        for line in path.read_text('utf-8-sig').splitlines(): result.update(json.loads(line))
    return result


def annotation_anchor(case, raw, witness):
    """Locate source sentences using existing annotations; log heuristic alignment."""
    if witness is None: return None
    text = case['text']
    boundaries = [0] + [m.end() for m in re.finditer(r'(?<=[.!?])\s+(?=[A-Z])|\n+', text)] + [len(text)]
    spans = [{'start': a, 'end': b, 'text': text[a:b]} for a, b in zip(boundaries, boundaries[1:]) if a < b]
    if witness['kind'] == 'optimal_face':
        direction = raw['obj_declaration']['direction'].lower()
        selected = [s for s in spans if direction in s['text'].lower()]
        if not selected: return None
        return {**selected[-1], 'row': witness['target_row'], 'alignment': 'official_objective_direction_sentence'}
    target = list(map(F, witness['target_row']['a'])) + [F(witness['target_row']['b'])]
    def vector(row):
        sign = -1 if row['op'] == '>=' else 1
        values = [F(v)*sign for v in row['a']] + [F(row['b'])*sign]
        scale = abs(values[0])+abs(values[1]) or abs(values[2]) or F(1)
        return [v/scale for v in values]
    scale = abs(target[0])+abs(target[1]) or abs(target[2]) or F(1)
    target = [v/scale for v in target]
    distances = []
    for i, row in enumerate(case['reference']['constraints']):
        vectors = [vector(row)]
        if row['op'] == '=': vectors.append([-v for v in vectors[0]])
        distances.append((min(sum(abs(a-b) for a, b in zip(target, v)) for v in vectors), i))
    distances.sort()
    if not distances or (len(distances) > 1 and distances[0][0] == distances[1][0]): return None
    distance, index = distances[0]
    declaration = raw['const_declarations'][index]
    direction = declaration.get('direction', '').strip().lower()
    if not direction: return None
    choices = [s for s in spans if direction in s['text'].lower()]
    if not choices: return None
    def score(span):
        literal = span['text'].lower()
        value = 0
        if 'limit' in declaration and str(declaration['limit']).lower() in literal: value += 4
        for key in ('var', 'x_var', 'y_var'):
            if key in declaration and str(declaration[key]).lower() in literal: value += 2
        return value
    choices.sort(key=lambda s: (-score(s), s['start']))
    if len(choices) > 1 and score(choices[0]) == score(choices[1]): return None
    return {**choices[0], 'row': witness['target_row'], 'alignment': 'official_constraint_direction_and_literal_match',
            'official_constraint_index': index, 'normalized_row_distance': str(distance)}


def prepare_round(batch, number):
    if number not in (1, 2, 3): raise ValueError('At most three rounds')
    cases = read(batch / 'T8-cases.private.json')
    validate_ladder_cohort(cases)
    raw = source_records(batch)
    histories = read(batch / 'ladder-observations.json') if number > 1 else []
    queue, contexts = [], []
    for case in cases:
        for arm in ARMS:
            previous = [o for o in histories if o['id'] == case['id'] and o['arm'] == arm]
            if previous and (previous[-1]['metrics']['success'] or previous[-1].get('terminal_failure')): continue
            before = case['screening_models'][0] if not previous else previous[-1]['new_model']
            peer = case['screening_models'][1]
            witnesses = compare_models(before, peer)['witnesses']
            anchor = annotation_anchor(case, raw[case['id']], witnesses[0] if witnesses else None)
            prepared = ladder_request(case, before, peer, arm, number, anchor, allow_missing_anchor=True)
            queue.append(prepared['request'])
            contexts.append({'id': case['id'], 'arm': arm, 'round': number, 'before': before,
                             'anchor_alignment': anchor, **prepared['scoring_context']})
    random.Random(2026102280+number).shuffle(queue)
    prior = [ROOT / '实验/任务板执行_2026-10-22_02/budget-spend.json', batch / 'harness-spend.json',
             batch / 'T8-screening/budget-spend.json', batch / 'T8-screening-expanded/budget-spend.json']
    prior += [batch / f'T8-round-{r}/budget-spend.json' for r in range(1, number)]
    details = {'phase': 'repair', 'round': number, 'case_manifest_sha256': sha(batch / 'T8-cases.private.json'),
               'max_rounds': 3, 'initial_candidate': 'A', 'fixed_peer': 'B',
               'primary': 'Any successful post-feedback output within at most three rounds; all 80 assigned problems remain in each arm denominator.',
               'early_stop': 'Stop that problem-arm after exact reference success or invalid response. Missing anchors are recorded, never fabricated or used to remove cases.',
               'anchor_policy': 'Annotation-assisted sentence retrieval. Select the closest unique normalized official constraint row, then a unique direction/limit/variable-matched sentence; optimal-face points use the objective-direction sentence. This is heuristic source localization, not independently validated semantic annotation.',
               'reference_policy': 'Official structured model only for scoring and annotation-assisted source localization; no reference model or correctness label is included in requests.',
               'metrics': {'compliance': 'Literal feasible membership of previous witness; correctness of that membership is recorded separately.',
                           'damage': 'Loss of any official constraint row previously implied by the nonempty candidate region.'},
               'intervals': 'Per-arm and per-stratum marginal Clopper-Pearson; per-round measurements use problem denominators, not pooled independent rounds.'}
    output = batch / f'T8-round-{number}'
    registered = register_queue(output, queue, details, prior, completion_tokens=150)
    save(output / 'contexts.private.json', contexts)
    return registered['estimate']


def score_round(batch, number):
    output = batch / f'T8-round-{number}'
    contexts = read(output / 'contexts.private.json')
    cases = {c['id']: c for c in read(batch / 'T8-cases.private.json')}
    histories = read(batch / 'ladder-observations.json') if number > 1 else []
    if any(o['round'] >= number for o in histories): raise ValueError('Round already scored')
    for context in contexts:
        case = cases[context['id']]
        arm = context['arm'].replace('+', '_')+f'_r{number}'
        candidate = load_candidate(output, case, arm)
        model = candidate.get('model')
        metrics = round_metrics(case['reference'], context['before'], model, context['previous_point'])
        histories.append({**context, 'new_model': model, 'metrics': metrics,
                          'terminal_failure': not candidate['valid'], 'failure': candidate.get('error')})
    save(output / 'observations.json', histories)
    save(batch / 'ladder-observations.json', histories)
    return {'round': number, 'responses': len(contexts), 'successful_responses': sum(o['metrics']['success'] for o in histories if o['round'] == number),
            'invalid_responses': sum(o['terminal_failure'] for o in histories if o['round'] == number)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare-screening', 'prepare-expanded', 'score-screening', 'prepare-round', 'score-round'))
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--round', type=int)
    args = parser.parse_args()
    action = {'prepare-screening': prepare_screening, 'prepare-expanded': prepare_expanded_screening, 'score-screening': score_screening,
              'prepare-round': prepare_round, 'score-round': score_round}[args.action]
    result = action(args.batch.resolve(), args.round) if args.action.endswith('round') else action(args.batch.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
