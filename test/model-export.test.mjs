import test from 'node:test';
import assert from 'node:assert/strict';
import katex from 'katex';
import { exportModel, modelLP } from '../shared/model-export.mjs';
import { symbolLatex } from '../shared/math-format.mjs';
import { demoModel } from '../shared/solver-model.mjs';

test('exports model data in actual selected formats', () => {
  assert.deepEqual(JSON.parse(exportModel(demoModel, 'json').text), demoModel);
  assert.match(exportModel(demoModel, 'py', 'gurobi', 17).text, /gurobi_direct/);
  assert.match(exportModel(demoModel, 'py', 'highs', 17).text, /time_limit.*17/);
  assert.match(exportModel(demoModel, 'tex').text, /\\documentclass\{article\}/);
  assert.match(modelLP(demoModel), /Maximize\n obj: 40 v_A \+ 30 v_B/);
  assert.match(modelLP(demoModel), /Generals\n v_A\n v_B\nEnd/);
  assert.throws(() => exportModel(demoModel, 'exe'), /Unsupported/);
  assert.throws(() => exportModel({}, 'lp'));
});

test('LP retains unbounded and negative bounds, zero-cost variables, binary domains and small coefficients', () => {
  const model = { ...demoModel, sense: 'minimize', variables: [
    { name: 'bounds', type: 'continuous', lower: null, upper: -2 },
    { name: 'free', type: 'continuous', lower: null, upper: null },
    { name: 'x_1', type: 'binary', lower: 0, upper: 1 }
  ], objective: { bounds: 1e-7, x_1: -2 }, constraints: [] };
  const lp = modelLP(model);
  assert.match(lp, /0.0000001 v_bounds - 2 v_x_1/);
  assert.match(lp, /-inf <= v_bounds <= -2/);
  assert.match(lp, /v_free free/);
  assert.match(lp, /Binaries\n v_x_1/);
});

test('indexed symbols render semantic subscripts instead of literal underscores', () => {
  assert.equal(symbolLatex('x_12'), 'x_{12}');
  assert.equal(symbolLatex('x_i_j'), 'x_{i,j}');
  assert.match(katex.renderToString(symbolLatex('x_12')), /<msub>/);
});
