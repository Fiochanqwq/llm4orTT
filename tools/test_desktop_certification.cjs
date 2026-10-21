// UI semantics tests without npm, a browser, or user profile access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const context = vm.createContext({
  k: { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
});
vm.runInContext(fs.readFileSync(path.join(root, 'src/inverse-certification.js'), 'utf8').replace(/^import .*;$/m, '').replace(/^export .*;$/m, ''), context);
function flatten(node) {
  if (!node || typeof node !== 'object') return String(node ?? '');
  if (Array.isArray(node)) return node.map(flatten).join(' ');
  return flatten(node.props?.children);
}
function find(node, id) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) return node.map(n => find(n, id)).find(Boolean);
  if (node.props?.id === id) return node;
  return find(node.props?.children, id);
}
const base = { samples: [{ id: 'history' }], deployment: { id: 'new-context' } };
let edited;
let input = context.inverseCertificationInput({
  draft: JSON.stringify(base), disabled: false, update: value => { edited = JSON.parse(value); }
});
assert.equal(find(input, 'inverse-noise-budget').props.value, '');
find(input, 'inverse-noise-budget').props.onChange({ target: { value: '0' } });
assert.deepEqual(edited.certification, { noise: { kind: 'absolute', budget: 0 }, threshold: 0 });
assert.deepEqual(edited.deployment, base.deployment);
input = context.inverseCertificationInput({
  draft: JSON.stringify(edited), disabled: false, update: value => { edited = JSON.parse(value); }
});
find(input, 'inverse-noise-budget').props.onChange({ target: { value: '' } });
assert.equal(edited.certification, undefined);
assert.deepEqual(edited.deployment, base.deployment);
const advanced = { ...base, certification: { noise: { kind: 'absolute', budgets: { history: 0.25 } }, threshold: 1 } };
input = context.inverseCertificationInput({
  draft: JSON.stringify(advanced), disabled: false, update: value => { edited = JSON.parse(value); }
});
assert.equal(find(input, 'inverse-noise-budget'), undefined);
find(input, 'inverse-risk-threshold').props.onChange({ target: { value: '2' } });
assert.deepEqual(edited.certification.noise, advanced.certification.noise);
const compatibility = {
  status: 'partial', deploymentSource: 'historical_context_replay', deploymentId: 'history',
  decisionCertificate: { status: 'unresolved', lowerBound: 0, upperBound: null, threshold: 1 }
};
let report = flatten(context.inverseCertificationReport({ analysis: { compatibility } }));
assert.match(report, /不是新场景测试/);
assert.match(report, /尚无有效界/);
assert.match(report, /现有证据还不能下结论/);
report = flatten(context.inverseCertificationReport({
  analysis: { compatibility: { ...compatibility, decisionCertificate: { status: 'safe' } }, supersededByModelProposal: true }
}));
assert.match(report, /已过期/);
assert.match(report, /不能用于保证当前规则/);
assert.equal(context.inverseCertificationReport({ analysis: {} }), null);
console.log(JSON.stringify({ checks: 13, status: 'passed' }));
