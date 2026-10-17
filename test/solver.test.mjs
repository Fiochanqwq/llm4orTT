import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import { SolverService } from '../server/solver.mjs';
import { demoModel, validateModel, pyomoSource } from '../shared/solver-model.mjs';
const directory = path.resolve('qa', 'solver-unit-' + new Date().toISOString().replace(/[:.]/g, '-'));
const service = new SolverService(directory);
const clone = () => structuredClone(demoModel);
async function completed(record) { const end = Date.now() + 50000; while (record.status === 'running' && Date.now() < end) await new Promise(resolve => setTimeout(resolve, 100)); assert.notEqual(record.status, 'running', 'worker did not terminate'); return record; }
async function solve(model) { return completed(service.start({ model, engine: 'highs', seconds: 15 })); }
test('real bundled Pyomo + HiGHS matches independently enumerated demo optimum', async () => {
  let best = -Infinity, pairs = [];
  for (let A = 0; A <= 20; A++) for (let B = 0; B <= 25; B++) if (2 * A + B <= 40 && A + 2 * B <= 50) {
    const profit = 40 * A + 30 * B;
    if (profit > best) { best = profit; pairs = [{ A, B }]; } else if (profit === best) pairs.push({ A, B });
  }
  const r = await solve(clone()); assert.equal(r.status, 'optimal', JSON.stringify(r)); assert.equal(r.objective, best); assert.deepEqual(pairs, [{ A: 10, B: 20 }]); assert.deepEqual(r.values, pairs[0]); assert.equal(r.check.feasible, true); assert.match(r.log, /HiGHS/);
  fs.writeFileSync(path.join(directory, 'enumeration.json'), JSON.stringify({ kind: 'software_demo_validation_not_research', domain: { A: [0, 20], B: [0, 25] }, best, pairs, solverRun: r.id }, null, 2));
});
test('continuous minimization and equality use actual fractional solution', async () => {
  const m = clone(); m.sense = 'minimize'; m.variables = [{ name: 'x', type: 'continuous', lower: null, upper: null }]; m.objective = { x: 3 }; m.constraints = [{ name: 'balance', terms: { x: 2 }, sense: '=', rhs: 3 }];
  const r = await solve(m); assert.equal(r.status, 'optimal'); assert.equal(r.values.x, 1.5); assert.equal(r.objective, 4.5); assert.equal(r.check.feasible, true);
});
test('infeasible and unbounded runs have no fabricated optimal values', async () => {
  const m = clone(); m.constraints.push({ name: 'impossible', terms: { A: 1 }, sense: '<=', rhs: -1 });
  const infeasible = await solve(m); assert.equal(infeasible.status, 'infeasible'); assert.equal(infeasible.objective, null); assert.equal(infeasible.values, null);
  const u = clone(); u.variables = [{ name: 'x', type: 'continuous', lower: 0, upper: null }]; u.objective = { x: 1 }; u.constraints = [];
  const unbounded = await solve(u); assert.equal(unbounded.status, 'unbounded'); assert.equal(unbounded.objective, null);
});
test('invalid fields, unknown variables, nonfinite numbers and Python text are rejected without execution', () => {
  const m = clone(); m.constraints[0].terms.typo = 1; assert.throws(() => validateModel(m), /unknown variable/);
  const r = service.start({ model: { ...clone(), code: 'import os; os.remove("x")' }, engine: 'highs', seconds: 15 }); assert.equal(r.status, 'rejected'); assert.equal(service.active, null);
  const n = clone(); n.objective.A = Infinity; assert.throws(() => validateModel(n), /finite/);
  assert.equal(service.start({ model: clone(), engine: 'shell', seconds: 15 }).status, 'rejected');
  assert.equal(service.start({ model: clone(), engine: 'highs', seconds: 5000 }).status, 'rejected');
  assert.match(pyomoSource(clone()), /SolverFactory\("appsi_highs"\)/);
});
test('optional Gurobi reports unavailable without silently falling back', () => {
  const r = service.start({ model: clone(), engine: 'gurobi', seconds: 15 }); assert.equal(r.status, 'unavailable'); assert.equal(r.engine, 'gurobi'); assert.equal(r.objective, undefined);
});
test('one active run, cancellation, and history survive a service restart', async () => {
  const r = service.start({ model: clone(), engine: 'highs', seconds: 15 });
  assert.throws(() => service.start({ model: clone(), engine: 'highs', seconds: 15 }), /已有/);
  service.stop(r.id); await completed(r); assert.equal(r.status, 'stopped'); assert.equal(r.objective, null);
  const restored = new SolverService(directory); assert.equal(restored.get(r.id).status, 'stopped'); assert.ok(restored.list().some(v => v.status === 'infeasible'));
});
