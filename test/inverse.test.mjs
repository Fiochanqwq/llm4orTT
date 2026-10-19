import test from 'node:test';
import assert from 'node:assert/strict';
import { applyProposal, inverseDemo, learnerView, runInversePipeline, solveInverse } from '../server/inverse.mjs';

test('learner prompt whitelist excludes oracle and holdout information', () => {
  const input = { ...inverseDemo(), truth: { secret: 88 }, test: ['never disclose'] };
  input.hypotheses[0].oracleWeight = 'secret';
  input.samples[0].model.oracle = 'secret';
  input.samples[0].features.night.hiddenWeight = 'secret';
  const view = learnerView(input);
  assert.ok(!JSON.stringify(view).includes('never disclose'));
  assert.ok(!JSON.stringify(view).includes('secret'));
});

test('proposal cannot rewrite history, known costs or hard constraints', () => {
  const input = inverseDemo();
  const proposal = { hypotheses: input.hypotheses, samples: input.samples.map(s => ({ ...s, decision: {}, model: {}, features: s.features })) };
  const result = applyProposal(input, proposal);
  assert.deepEqual(result.samples, input.samples);
  proposal.samples.pop();
  assert.throws(() => applyProposal(input, proposal), /样本/);
});

test('pipeline rejects worse proposals and retains previous recoverable result', async () => {
  const input = inverseDemo(); let calls = 0;
  const solve = async () => ({ status: 'optimal', meanResidual: calls++ ? 2 : 1, anomalies: [{ id: 'x', residual: 1 }], theta: {} });
  const generator = async function* () { yield { text: JSON.stringify({ hypotheses: input.hypotheses, samples: input.samples.map(s => ({ id: s.id, features: s.features })) }) }; };
  const result = await runInversePipeline(input, { solve, generator, config: { id: 'fake', model: 'fixture' }, useLLM: true });
  assert.equal(result.meanResidual, 1);
  assert.equal(result.stopReason, 'proposal_not_improved');
  assert.equal(result.history[1].accepted, false);
});

test('invalid round budget never invokes solver', async () => {
  await assert.rejects(runInversePipeline(inverseDemo(), { rounds: 6, solve: () => assert.fail() }), /1–5/);
});

test('pre-aborted solve exits without spawning a worker', async () => {
  await assert.rejects(solveInverse(inverseDemo(), { signal: AbortSignal.abort() }), /取消/);
});
