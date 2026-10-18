import test from 'node:test';
import assert from 'node:assert/strict';
import { evidenceDecision } from '../server/evidence-routing.mjs';
import { agentLimits as limits } from '../server/agent-policy.mjs';
import { methodLabel, interactiveMethodIds, methodPresets } from '../shared/methods.mjs';
const decide = (e, options = {}) => evidenceDecision(e, { limits, ...options });

test('mismatches repair internally or fall back when budgets are exhausted', () => {
  for (const flag of ['missing_prompt_numbers','hallucinated_numbers','integrality_mismatch','sense_mismatch','has_scaling_issue','monotonicity_violated']) {
    const e = { [flag]: true, prompt_audited: true };
    assert.equal(decide(e, { status: 'infeasible' }).action, 'repair');
    for (const options of [{ calls: 3 }, { solves: 2 }, { repair: false }]) assert.equal(decide(e, options).action, 'fallback');
  }
});
test('anomalies need semantic clearance before asking and respect interaction budgets', () => {
  for (const status of ['infeasible','unbounded','infeasible_or_unbounded']) {
    assert.equal(decide({ prompt_audited:true }, { status }).action, 'fallback');
    assert.equal(decide({ prompt_audited:true }, { status, review:'no_issue_found' }).action, 'clarify');
    assert.equal(decide({ prompt_audited:true }, { status, review:'no_issue_found', clarifications:2 }).action, 'fallback');
  }
});
test('absent diagnostics and ambiguous coverage cannot certify a result', () => {
  for (const e of [null, { diagnostic_error:'worker failure' }]) assert.equal(decide(e).action, 'fallback');
  const ambiguous = { missing_prompt_numbers:true, number_coverage_ambiguous:true, prompt_audited:true };
  assert.equal(decide(ambiguous).action, 'continue');
  assert.equal(decide(ambiguous, { status:'unbounded', review:'no_issue_found' }).action, 'fallback');
  assert.equal(decide({}, { status:'optimal', review:'no_issue_found' }).action, 'deliver');
  assert.equal(decide({}, { status:'optimal' }).action, 'fallback');
});
test('ablation is available to experiments, translated, and absent from interactive choices', () => {
  assert.ok(methodPresets.no_evidence);
  assert.ok(!interactiveMethodIds.includes('no_evidence'));
  assert.match(methodLabel('no_evidence'), /关闭程序证据/);
});
