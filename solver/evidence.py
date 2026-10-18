"""Deterministic LP evidence. No model-generated Python is executed.

Number coverage is a screen, NOT a semantic certificate. Elastic conflicts are
one minimum-sum relaxation (not an IIS); units affect which rows get slack.
"""
import math
import re
import time

VERSION = 'programmatic-evidence-1'
TOL = 1e-7


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-8)


def prompt_numbers(text):
    # Do not treat digits in identifiers (x1) as quantities. Keep signed values.
    return sorted(set(float(x.replace(',', '')) for x in re.findall(
        r'(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?|(?<=[\u4e00-\u9fff])[-+]?\d+(?:\.\d+)?', text)
        if math.isfinite(float(x.replace(',', '')))))


def inspect_model(model, data, prompt=''):
    """Read coefficients from actual Pyomo expressions, not a model's claims."""
    import pyomo.environ as pyo
    from pyomo.repn import generate_standard_repn
    constants = []
    obj = generate_standard_repn(model.objective.expr)
    constants.extend(float(v) for v in obj.linear_coefs)
    if obj.constant:
        constants.append(float(obj.constant))
    scaling = []
    for original, row in zip(data['constraints'], model.constraints.values()):
        rep = generate_standard_repn(row.body)
        rhs = pyo.value(row.upper if row.has_ub() else row.lower) - float(rep.constant or 0)
        vals = [float(v) for v in rep.linear_coefs] + [float(rhs)]
        constants.extend(vals)
        nonzero = [abs(v) for v in vals if v]
        if nonzero and max(nonzero) / min(nonzero) > 10000:
            scaling.append({'name': original['name'], 'ratio': max(nonzero) / min(nonzero), 'expression': original})
    for x in model.x.values():
        constants.extend(float(v) for v in (x.lb, x.ub) if v is not None)
    numbers = prompt_numbers(prompt)
    constants = sorted(set(v for v in constants if v))
    # Unit equivalence is explicit and limited; never allow arbitrary products.
    equivalents = {v: [abs(v)] for v in numbers if v}
    conversions = []
    for a, b, factor in [('万元', '元', 10000), ('吨', '千克', 1000), ('千克', '克', 1000), ('小时', '分钟', 60)]:
        # Both units must actually occur as distinct units in the public prompt.
        if a in prompt and re.search(r'(?<![万千])' + re.escape(b), prompt):
            for match in re.finditer(r'(\d+(?:\.\d+)?)\s*' + re.escape(a), prompt):
                value = float(match[1]); equivalents.setdefault(value, [value]).append(value * factor)
                if re.search(r'(?:模型|统一).{0,6}(?:以|用|为)' + re.escape(b), prompt):
                    equivalents[value] = [value * factor]
                conversions.append({'source': value, 'from': a, 'to': b, 'value': value * factor})
    magnitudes = [abs(v) for v in constants]
    missing = [v for v, aliases in equivalents.items() if not any(close(a, c) for a in aliases for c in magnitudes)]
    # Counts, labels and coefficients of explicitly eliminated variables can
    # disappear legitimately. Only literal algebraic RHS omissions are anchored
    # enough to block automatically in isolation; retain all raw differences.
    direct_rhs = [float(v) for v in re.findall(r'(?:<=|>=|=|≤|≥)\s*([-+]?\d+(?:\.\d+)?)', prompt)]
    ambiguous_missing = bool(missing) and not any(close(v, r) for v in missing for r in direct_rhs)
    allowed = [1.0] + [a for aliases in equivalents.values() for a in aliases]
    hallucinated = [v for v in constants if not any(close(abs(v), a) for a in allowed)] if numbers else []
    # Only universal domain phrases justify a deterministic domain mismatch.
    all_integer = bool(re.search(r'(?:均|都|全部|所有|all).{0,16}(?:整数|integer)|(?:产量|数量|变量)为非负整数|nonnegative integers', prompt, re.I))
    all_binary = bool(re.search(r'(?:均|都|全部|所有|all).{0,16}(?:二元|binary)', prompt, re.I))
    integer = sum(x.is_integer() and not x.is_binary() for x in model.x.values())
    binary = sum(x.is_binary() for x in model.x.values())
    domain_mismatches = []
    for name, x in model.x.items():
        prefix = r'(?<![A-Za-z0-9_])' + re.escape(name) + r'\s*(?:必须|应|must)?\s*(?:为|是|be|is)\s*(?:非负|nonnegative)?\s*'
        if re.search(prefix + r'(?:整数|integer)', prompt, re.I) and not x.is_integer():
            domain_mismatches.append(name)
        if re.search(prefix + r'(?:二元|binary)', prompt, re.I) and not x.is_binary():
            domain_mismatches.append(name)
    max_intent = bool(re.search(r'最大化|maximize|maximise', prompt, re.I))
    min_intent = bool(re.search(r'最小化|minimize|minimise', prompt, re.I))
    sense = 'minimize' if model.objective.sense == pyo.minimize else 'maximize'
    mismatch = (max_intent != min_intent) and sense != ('maximize' if max_intent else 'minimize')
    return {'version': VERSION, 'source': 'pyomo_standard_repn', 'objective_sense': sense,
            'variable_count': len(model.x), 'integer_variable_count': integer, 'binary_variable_count': binary,
            'nonzero_constants': constants, 'prompt_numbers': numbers, 'unit_conversions': conversions,
            'missing_prompt_numbers': bool(missing), 'missing_prompt_number_values': missing,
            'number_coverage_ambiguous': ambiguous_missing,
            'hallucinated_numbers': bool(hallucinated), 'hallucinated_number_values': hallucinated,
            'integrality_mismatch': bool(domain_mismatches) or (all_integer and integer + binary != len(model.x)) or (all_binary and binary != len(model.x)),
            'integrality_mismatch_variables': domain_mismatches,
            'sense_mismatch': bool(mismatch), 'has_scaling_issue': bool(scaling), 'scaling_rows': scaling,
            'coverage': 'numeric_screen_only_not_semantic_proof', 'prompt_audited': bool(prompt.strip()),
            'is_trivial_solution': False, 'hit_artificial_bound': False, 'artificial_bound_variables': [],
            'infeasible_conflict_constraints': [], 'monotonicity_violated': False,
            'monotonicity_anomalies': [], 'auxiliary_solves': 0, 'probes': [], 'probe_status': 'not_requested'}


def postsolve(evidence, model, data, result, solver, allowance=0, perturb=False):
    import pyomo.environ as pyo
    start = time.monotonic()
    status, values = result['status'], result.get('values') or {}
    if status == 'optimal':
        evidence['is_trivial_solution'] = abs(result['objective']) <= TOL or bool(values) and all(abs(v) <= TOL for v in values.values())
        for v in data['variables']:
            upper = v['upper']
            if upper is not None and upper >= 1e6 and v['name'] in values and close(values[v['name']], upper):
                # A public business cap is not automatically artificial.
                if not any(close(upper, n) for n in evidence['prompt_numbers']):
                    evidence['artificial_bound_variables'].append(v['name'])
        evidence['hit_artificial_bound'] = bool(evidence['artificial_bound_variables'])
    evidence['unbounded_variable_candidates'] = [v['name'] for v in data['variables'] if v['upper'] is None or v['lower'] is None] if status in ('unbounded', 'infeasible_or_unbounded') else []

    def resolve(m):
        evidence['auxiliary_solves'] += 1  # Failed attempts count, too.
        r = solver.solve(m, tee=False, load_solutions=False)
        if str(r.solver.termination_condition) == 'optimal' and len(r.solution):
            m.solutions.load_from(r)
            return float(pyo.value(m.objective))
        return None

    if status == 'infeasible' and allowance:
        relaxed = model.clone()
        relaxed.constraints.deactivate()
        relaxed.objective.deactivate()
        # `slack` is a reserved result suffix name in Pyomo solver adapters.
        relaxed.diagnostic_slack = pyo.Var(range(len(data['constraints'])), domain=pyo.NonNegativeReals)
        relaxed.elastic = pyo.ConstraintList()
        for i, c in enumerate(data['constraints']):
            lhs = sum(v * relaxed.x[k] for k, v in c['terms'].items() if v)
            if c['sense'] in ('<=', '='):
                relaxed.elastic.add(lhs - relaxed.diagnostic_slack[i] <= c['rhs'])
            if c['sense'] in ('>=', '='):
                relaxed.elastic.add(lhs + relaxed.diagnostic_slack[i] >= c['rhs'])
        relaxed.del_component('objective')
        relaxed.objective = pyo.Objective(expr=sum(relaxed.diagnostic_slack.values()))
        optimum = resolve(relaxed)
        evidence['elastic_status'] = 'optimal' if optimum is not None else 'unresolved_bounds_or_domains'
        evidence['elastic_note'] = 'One minimum L1 row relaxation; not an IIS. Variable bounds and integrality retained.'
        if optimum is not None:
            evidence['infeasible_conflict_constraints'] = [
                {'name': c['name'], 'expression': c, 'slack': float(pyo.value(relaxed.diagnostic_slack[i]))}
                for i, c in enumerate(data['constraints']) if pyo.value(relaxed.diagnostic_slack[i]) > 1e-5]
    if perturb:
        candidates = [(i, c) for i, c in enumerate(data['constraints']) if c['sense'] != '=' and c['rhs'] != 0]
        if status != 'optimal':
            evidence['probe_status'] = 'skipped_nonoptimal'
        elif allowance - evidence['auxiliary_solves'] < 2:
            evidence['probe_status'] = 'skipped_budget_requires_two_solves'
        elif not candidates:
            evidence['probe_status'] = 'skipped_no_supported_parameter'
        else:
            i, c = candidates[0]  # Frozen deterministic selection; never search for a significant result.
            for multiplier in (.9, 1.1):
                perturbed = model.clone()
                lhs = sum(v * perturbed.x[k] for k, v in c['terms'].items() if v)
                rhs = c['rhs'] * multiplier
                perturbed.constraints[i + 1].set_value(lhs <= rhs if c['sense'] == '<=' else lhs >= rhs)
                objective = resolve(perturbed)
                delta = rhs - c['rhs']
                relaxed_direction = delta > 0 if c['sense'] == '<=' else delta < 0
                expected = 1 if relaxed_direction == (data['sense'] == 'maximize') else -1
                violation = objective is not None and expected * (objective - result['objective']) < -1e-6 * max(1, abs(result['objective']))
                probe = {'parameter': c['name'] + '.rhs', 'multiplier': multiplier, 'objective': objective, 'expected_direction': expected, 'violated': violation}
                evidence['probes'].append(probe)
                if violation:
                    evidence['monotonicity_anomalies'].append(probe)
            evidence['probe_status'] = 'completed' if all(p['objective'] is not None for p in evidence['probes']) else 'inconclusive'
            evidence['monotonicity_violated'] = bool(evidence['monotonicity_anomalies'])
    evidence['diagnostic_elapsed_ms'] = round((time.monotonic() - start) * 1000, 3)
    return evidence
