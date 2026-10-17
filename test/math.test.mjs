import test from 'node:test';
import assert from 'node:assert/strict';
import katex from 'katex';
import { normalizeMathMarkdown, modelLatex } from '../shared/math-format.mjs';
import { demoModel } from '../shared/solver-model.mjs';
test('common LaTeX delimiters and fenced math normalize without changing code', () => {
  assert.match(normalizeMathMarkdown('Value \\(x^2\\).'), /\$x\^2\$/);
  assert.match(normalizeMathMarkdown('\\[\\frac{1}{2}\\]'), /\$\$\n\\frac\{1\}\{2\}\n\$\$/);
  assert.match(normalizeMathMarkdown('```latex\n\\sum_i x_i = 3\n```'), /\$\$\n\\sum_i x_i = 3\n\$\$/);
  assert.match(normalizeMathMarkdown('```python\ns = "\\[x\\]"\n```'), /s = "\\\[x\\\]"/);
  assert.match(normalizeMathMarkdown('`\\(literal\\)`'), /`\\\(literal\\\)`/);
  assert.match(normalizeMathMarkdown('```latex\n\\frac{'), /^```latex/); // incomplete stream stays as code
});
test('model formulas compile into accessible rendered math with safe identifiers', () => {
  const model = structuredClone(demoModel); model.variables[0].name = 'item_A'; model.objective = { item_A: -40, B: 30 }; model.constraints = [{ name: 'c', terms: { item_A: 2, B: -1 }, sense: '>=', rhs: -10 }];
  const tex = modelLatex(model), html = katex.renderToString(tex, { displayMode: true, trust: false });
  assert.ok(tex.includes('\\mathrm{item}_{A}')); assert.match(tex, /-40/); assert.match(html, /katex-html/); assert.match(html, /<math/);
});
