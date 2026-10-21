// Semantic React-tree checks; no browser, npm install, or real profile access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const context = vm.createContext({
  k: { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
});
vm.runInContext(fs.readFileSync(path.join(root, 'src/inverse-certification.js'), 'utf8').replace(/^import .*;$/m, '').replace(/^export .*;$/m, ''), context);
const results = [];
function test(name, fn) {
  fn();
  results.push({ name, status: 'passed' });
}
function flatten(node) {
  if (node === false || node === true || node == null) return '';
  if (typeof node !== 'object') return String(node);
  if (Array.isArray(node)) return node.map(flatten).join(' ');
  return flatten(node.props?.children);
}
function find(node, id) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) return node.map(n => find(n, id)).find(Boolean);
  if (node.props?.id === id) return node;
  return find(node.props?.children, id);
}
function collect(node, type) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(n => collect(n, type));
  return [...(node.type === type ? [node] : []), ...collect(node.props?.children, type)];
}
const base = {
  samples: [{ id: 'h1' }, { id: 'h2' }],
  deployment: { id: 'new-context', decision: { x: 0 } },
  certification: {
    noise: { kind: 'absolute', budget: 0.1 }, threshold: 0.25,
    maxSeconds: 5, maxOracleCalls: 80
  }
};
let edited;
function render(data, disabled = false) {
  edited = undefined;
  return context.inverseCertificationInput({
    draft: JSON.stringify(data), disabled,
    update: value => { edited = JSON.parse(value); }
  });
}
const compatibility = {
  status: 'complete', note: '原预算检查完成。',
  deploymentSource: 'provided_context', deploymentId: 'new-context',
  noiseModel: { kind: 'absolute', budget: 0 },
  assumptionAudit: { note: '输入上限未被独立证明，训练拟合好不是依据。' },
  decisionGuidance: {
    status: 'risk_witness', scope: 'declared_upper_budget',
    note: '较宽预算已找到风险，不能沿用较紧预算的安全结论。'
  },
  decisionCertificate: {
    status: 'safe', lowerBound: 0, upperBound: 0, threshold: 0.1,
    chosenDecision: { x: 1 }, note: '仅原误差预算下成立。'
  },
  noiseSensitivity: {
    status: 'sensitive', nominalStatus: 'safe',
    upperNoise: { kind: 'absolute', budget: 0.4 },
    upperCertificate: { status: 'risk_witness', lowerBound: 0.2, upperBound: 0.2 },
    note: '较大误差下出现风险。'
  }
};
test('optional upper budget stays blank and does not become zero', () => {
  const node = render(base);
  assert.equal(find(node, 'inverse-noise-upper').props.value, '');
  assert.equal(edited, undefined);
  const label = flatten(node);
  assert.match(label, /留空不检查|更大的上限仍是输入假设/);
});
test('explicit upper budget preserves nominal settings and deployment', () => {
  const node = render(base);
  find(node, 'inverse-noise-upper').props.onChange({ target: { value: '0.4' } });
  assert.deepEqual(edited.certification.noise, base.certification.noise);
  assert.deepEqual(edited.certification.sensitivity, { upperNoise: { kind: 'absolute', budget: 0.4 } });
  assert.equal(edited.certification.threshold, 0.25);
  assert.equal(edited.certification.maxOracleCalls, 80);
  assert.deepEqual(edited.deployment, base.deployment);
});
test('clearing optional upper removes sensitivity only', () => {
  const value = structuredClone(base);
  value.certification.sensitivity = { upperNoise: { kind: 'absolute', budget: 0.4 }, maxSeconds: 7 };
  const node = render(value);
  find(node, 'inverse-noise-upper').props.onChange({ target: { value: '' } });
  assert.equal(edited.certification.sensitivity, undefined);
  assert.deepEqual(edited.certification, base.certification);
  assert.deepEqual(edited.deployment, base.deployment);
});
test('invalid numeric upper does not mutate input', () => {
  for (const value of ['-1', 'NaN', 'Infinity']) {
    const node = render(base);
    find(node, 'inverse-noise-upper').props.onChange({ target: { value } });
    assert.equal(edited, undefined);
  }
});
test('upper below nominal is visible and is never silently increased', () => {
  const value = structuredClone(base);
  value.certification.sensitivity = { upperNoise: { kind: 'absolute', budget: 0 } };
  const node = render(value);
  assert.equal(find(node, 'inverse-noise-upper').props.value, 0);
  assert.match(flatten(node), /上限小于原预算/);
  assert.match(flatten(node), /不会自动替你放大/);
  assert.equal(edited, undefined);
});
test('per-history nominal and upper budgets remain protected', () => {
  const value = structuredClone(base);
  value.certification.noise = { kind: 'absolute', budgets: { h1: 0, h2: 0.1 } };
  value.certification.sensitivity = {
    upperNoise: { kind: 'absolute', budgets: { h1: 0.3, h2: 0.5 } }
  };
  const node = render(value);
  assert.equal(find(node, 'inverse-noise-budget'), undefined);
  assert.equal(find(node, 'inverse-noise-upper'), undefined);
  assert.match(flatten(node), /逐条敏感性上限/);
  find(node, 'inverse-risk-threshold').props.onChange({ target: { value: '1' } });
  assert.deepEqual(edited.certification.noise, value.certification.noise);
  assert.deepEqual(edited.certification.sensitivity, value.certification.sensitivity);
});
test('per-history upper alone disables simplified upper editor', () => {
  const value = structuredClone(base);
  value.certification.sensitivity = {
    upperNoise: { kind: 'absolute', budgets: { h1: 0.3, h2: 0.5 } }
  };
  const node = render(value);
  assert.ok(find(node, 'inverse-noise-budget'));
  assert.equal(find(node, 'inverse-noise-upper'), undefined);
  find(node, 'inverse-risk-threshold').props.onChange({ target: { value: '2' } });
  assert.deepEqual(edited.certification.sensitivity, value.certification.sensitivity);
});
test('upper risk is the first conclusion even when nominal result is safe', () => {
  const node = context.inverseCertificationReport({ analysis: { compatibility } });
  const headings = collect(node, 'h3').map(flatten);
  assert.match(headings[0], /本次综合结论.*已找到风险.*不能给安全保证/);
  assert.match(headings[1], /原误差预算下的结果.*损失不超过阈值/);
  const text = flatten(node);
  assert.ok(text.indexOf('本次综合结论') < text.indexOf('原误差预算下的结果'));
  assert.match(text, /上限本身仍未获独立验证/);
  assert.match(text, /训练拟合好不是依据/);
});
test('stale applies to the overall guidance as well as nominal result', () => {
  const node = context.inverseCertificationReport({
    analysis: { compatibility, supersededByModelProposal: true }
  });
  const text = flatten(node);
  assert.match(text, /原模型的决策保证（已过期）/);
  assert.match(text, /原模型综合结论（已过期）/);
  assert.match(text, /不能用于保证当前规则/);
  assert.doesNotMatch(text, /本次综合结论：/);
});
test('nominal incompatibility is retained beside upper endpoint findings', () => {
  const value = structuredClone(compatibility);
  value.status = 'incompatible';
  value.decisionCertificate.status = 'incompatible';
  value.decisionCertificate.lowerBound = null;
  value.decisionCertificate.upperBound = null;
  value.decisionGuidance.status = 'conditional_safe';
  value.noiseSensitivity.nominalStatus = 'incompatible';
  value.noiseSensitivity.upperCertificate.status = 'safe';
  const text = flatten(context.inverseCertificationReport({ analysis: { compatibility: value } }));
  assert.match(text, /原来较紧的预算仍与历史不相容/);
  assert.match(text, /上限处的结果没有消除这条事实/);
  assert.match(text, /尚无有效界/);
});
test('disabled inputs remain disabled and malformed JSON is ignored', () => {
  const node = render(base, true);
  for (const id of ['inverse-noise-budget', 'inverse-risk-threshold', 'inverse-noise-upper']) {
    assert.equal(find(node, id).props.disabled, true);
  }
  assert.equal(context.inverseCertificationInput({ draft: '{bad', disabled: false, update() {} }), null);
  assert.equal(context.inverseCertificationReport({ analysis: {} }), null);
});
console.log(JSON.stringify({ status: 'passed', checks: results.length, checksDetail: results }, null, 2));
