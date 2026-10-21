import test from 'node:test';
import assert from 'node:assert/strict';
import { instance, evaluate } from '../scripts/research-language-once.mjs';
import { learnerView, applyProposal } from '../server/inverse.mjs';

function fixture() {
  const { input, task } = instance();
  // Explicit test fixture, never counted as a model observation.
  const proposal = {
    hypotheses: [{ id: 'transfer', lower: 0, upper: 20 }],
    samples: input.samples.map(s => ({ id: s.id,
      features: { transfer: { kind: 'linear', terms: { handover: 1 } } } })),
  };
  return { proposedInput: applyProposal(input, proposal), task };
}

test('hidden truth and deployment outcomes never enter the production learner view', () => {
  const { input, task } = instance();
  const view = learnerView({ ...input, truth: task.hiddenTruth, deployment: task.deployment });
  assert.equal(Object.hasOwn(view, 'truth'), false);
  assert.equal(Object.hasOwn(view, 'deployment'), false);
  assert.deepEqual(view.hypotheses, []);
  assert.ok(view.samples.every(s => Object.keys(s.features).length === 0));
});

test('exact truth evaluation distinguishes bad release from zero historical fit error', () => {
  const result = evaluate(fixture());
  assert.equal(result.science.trueRegret, '2/5');
  assert.equal(result.science.meanTrainingResidual, 0);
  assert.equal(result.science.metrics.dangerousPlans, 1);
  assert.equal(result.science.metrics.dangerousPlanReleaseRate, 1);
  assert.equal(result.science.metrics.postAuditDangerousPlanReleaseRate, null);
});

test('danger is strictly above the threshold; zero dangerous denominator remains null', () => {
  const data = fixture();
  data.task.dangerThreshold = 0.4;
  const result = evaluate(data);
  assert.equal(result.science.dangerous, false);
  assert.equal(result.science.metrics.dangerousPlanReleaseRate, null);
});

test('context-specific memorization fails rather than silently replacing model features', () => {
  const data = fixture();
  data.proposedInput.samples[1].features.transfer.terms.handover = 2;
  assert.throws(() => evaluate(data), /inconsistent features/);
});
