import test from 'node:test';
import assert from 'node:assert/strict';
import { preflightModel } from '../shared/model-preflight.mjs';
import { demoModel } from '../shared/solver-model.mjs';
import { taskFor, modelFingerprint } from '../server/agent-policy.mjs';

test('bounded necessary checks retain feasible examples and do not enumerate', () => {
  assert.equal(preflightModel(demoModel).status, 'no_obvious_conflict');
  const model = structuredClone(demoModel);
  model.variables = [{ name: 'A', type: 'continuous', lower: null, upper: null }, { name: 'B', type: 'continuous', lower: 0, upper: 1 }];
  model.constraints = [{ name: 'zero', terms: { A: 0, B: 1 }, sense: '<=', rhs: 1 }];
  assert.equal(preflightModel(model).status, 'no_obvious_conflict');
});

test('negative single-variable coefficients, equality and integer domains tighten correctly', () => {
  const model = structuredClone(demoModel);
  model.constraints = [{ name: 'lower', terms: { A: -2 }, sense: '<=', rhs: -6 }, { name: 'upper', terms: { A: 1 }, sense: '<=', rhs: 2 }];
  assert.equal(preflightModel(model).status, 'conflict');
  model.constraints = [{ name: 'fraction', terms: { A: 2 }, sense: '=', rhs: 3 }];
  assert.equal(preflightModel(model).status, 'conflict');
  model.variables[0].type = 'continuous';
  assert.equal(preflightModel(model).status, 'no_obvious_conflict');
});

test('multi-variable interval conflicts are detected without assuming semantic correctness', () => {
  const model = structuredClone(demoModel);
  model.variables.forEach(v => v.upper = 2);
  model.constraints = [{ name: 'demand', terms: { A: 1, B: 1 }, sense: '>=', rhs: 5 }];
  assert.equal(preflightModel(model).status, 'conflict');
  model.constraints[0].rhs = 4;
  assert.equal(preflightModel(model).status, 'no_obvious_conflict');
});

test('preflight does not reject any feasible small integer fixture, checked by independent enumeration', () => {
  // Enumeration is test-only: a finite independent oracle, never part of the application.
  for (let a = -2; a <= 2; a++) for (let b = -2; b <= 2; b++) for (let rhs = -3; rhs <= 3; rhs++) {
    if (!a && !b) continue;
    for (const sense of ['<=', '>=', '=']) {
      const model = structuredClone(demoModel); model.variables.forEach(v => { v.lower = -2; v.upper = 2; });
      model.constraints = [{ name: 'test', terms: { A: a, B: b }, sense, rhs }];
      let feasible = false;
      for (let x = -2; x <= 2; x++) for (let y = -2; y <= 2; y++) if (sense === '<=' ? a*x+b*y <= rhs : sense === '>=' ? a*x+b*y >= rhs : a*x+b*y === rhs) feasible = true;
      if (feasible) assert.equal(preflightModel(model).status, 'no_obvious_conflict');
    }
  }
});

test('model fingerprint ignores display labels and ordering but preserves mathematical changes', () => {
  const m = structuredClone(demoModel); m.name = 'renamed'; m.constraints.reverse(); m.constraints[0].name = 'renamed'; m.variables.reverse();
  assert.equal(modelFingerprint(m), modelFingerprint(demoModel));
  m.constraints[0].rhs++;
  assert.notEqual(modelFingerprint(m), modelFingerprint(demoModel));
});

test('saved task snapshots retain counters on restart without mutating historical evidence', () => {
  const task = { id: 'a', rootUserId: 'u', calls: 3, solves: 1, clarifications: 2, inputs: [], attempts: [] };
  const conversation = JSON.parse(JSON.stringify({ messages: [{ automation: { stage: 'clarification', task } }] }));
  const next = taskFor(conversation, { id: 'u2', content: 'new fact' }, false);
  next.calls++;
  assert.equal(next.calls, 4); assert.equal(conversation.messages[0].automation.task.calls, 3);
});
