// One definition feeds validation and the provider's textual JSON contract.
// Keep string envelopes for compatibility with all existing providers.
export const protocolVersion = 'llm4orovo.submission.v3';
export const reviewVersion = 'llm4orovo.review.v3';
const string = (maxLength = 100, minLength = 1) => ({ type: 'string', minLength, maxLength });
const enumeration = (...values) => ({ enum: values });
const list = (items, maxItems = 1000, minItems = 0) => ({ type: 'array', items, minItems, maxItems });
const object = properties => ({ type: 'object', additionalProperties: false, required: Object.keys(properties), properties });
const nullable = schema => ({ anyOf: [{ type: 'null' }, schema] });
const number = { type: 'number', minimum: -1e9, maximum: 1e9 };
const ids = (min = 0, max = 1000) => list(string(160), max, min);
export const dispositions = ['encoded', 'pending_clarification', 'deferred_to_budget_gate', 'not_applicable'];
export const budgetSchema = object({ factId: string(80), gapId: string(80), lower: number, upper: number, unit: string(80),
  costTerms: { type: 'object', additionalProperties: number }, confirmedFixed: { const: true }, onlyCostCap: { const: true }, otherConditionsComplete: { const: true } });
export const contractSchema = object({
  format: { const: protocolVersion }, modelPurpose: enumeration('final_task', 'budget_threshold_base'),
  facts: list(object({ id: string(80), kind: string(80), sourceRefs: ids(1, 16), unit: string(80, 0),
    value: { anyOf: [{ type: 'null' }, { type: 'boolean' }, string(1000, 0), number, object({ lower: number, upper: number })] }, supersedes: ids(0, 100) })),
  bindings: list(object({ factIds: ids(1, 100), targetRefs: ids(1), disposition: enumeration(...dispositions), reason: string(1000, 0) }), 1500),
  gaps: list(object({ id: string(80), factId: string(80), kind: string(80) }), 50),
  budget: nullable(budgetSchema)
});
export const reviewSchema = object({
  format: { const: reviewVersion }, status: enumeration('no_issue_found', 'mismatch', 'uncertain'),
  diagnostics: list(object({ code: string(80), factIds: ids(), targetIds: ids(), gapIds: ids(0, 50), sourceRefs: ids(1, 16), evidence: string(1000), repairable: { type: 'boolean' } }), 100),
  factIds: ids(), targetIds: ids(0, 1500), gapIds: ids(0, 50), budgetApplicability: enumeration('supported', 'unsupported', 'uncertain', 'not_applicable')
});
export const questionSchema = object({ gapId: string(80), field: string(80), question: string(240), impact: string(160) });
export const budgetRule = 'A fixed approved budget may have an UNKNOWN exact amount and a KNOWN interval [L,U] (L=U is allowed). This is supported when it ONLY caps the SAME fully known linear minimization cost, all other facts are complete and independent, and there are no omitted fixed fees, objective constants, taxes, conversion or other unknown conditions. Do NOT require the exact budget to be known. Do NOT infer irrelevance from the modeler\'s arithmetic: the application uses actual solver evidence to compare the threshold with [L,U]. The base model deliberately omits ONLY this cap and is not the final task.';

const previews = value => value === undefined ? '(missing)' : JSON.stringify(value)?.slice(0, 800);
export class ProtocolError extends Error {
  constructor(code, path, expected, received, options = {}) {
    super(`${code} at ${path}: expected ${expected}`);
    this.name = 'ProtocolError';
    this.issue = { layer: options.layer || 'schema', code, path, expected, received: previews(received), recoverable: options.recoverable !== false, ...options };
  }
}
export function issue(code, path, expected, received, options) { throw new ProtocolError(code, path, expected, received, options); }
export function assertShape(value, schema, path = '$') {
  if (schema.anyOf) {
    if (schema.anyOf.some(s => { try { assertShape(value, s, path); return true; } catch { return false; } })) return;
    return issue('FIELD_TYPE', path, 'one of ' + schema.anyOf.map(s => s.type).join('/'), value);
  }
  if (Object.hasOwn(schema, 'const') && value !== schema.const) issue('FIELD_VALUE', path, JSON.stringify(schema.const), value);
  if (schema.enum && !schema.enum.includes(value)) issue('FIELD_VALUE', path, schema.enum.join(' | '), value);
  if (!schema.type) return;
  const correctType = schema.type === 'null' ? value === null : schema.type === 'array' ? Array.isArray(value)
    : schema.type === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value)
      : typeof value === schema.type;
  if (!correctType) issue('FIELD_TYPE', path, schema.type, value);
  if (schema.type === 'string' && (value.length < (schema.minLength ?? 0) || value.length > (schema.maxLength ?? Infinity))) issue('FIELD_LENGTH', path, `${schema.minLength ?? 0}..${schema.maxLength ?? Infinity} characters`, value);
  if (schema.type === 'number' && (!Number.isFinite(value) || value < schema.minimum || value > schema.maximum)) issue('FIELD_NUMBER', path, 'finite number within limits', value);
  if (schema.type === 'array') {
    if (value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? Infinity)) issue('FIELD_LENGTH', path, `${schema.minItems ?? 0}..${schema.maxItems ?? Infinity} entries`, value.length);
    value.forEach((x, i) => assertShape(x, schema.items, `${path}[${i}]`));
  }
  if (schema.type === 'object') {
    for (const k of schema.required || []) if (!Object.hasOwn(value, k)) issue('FIELD_REQUIRED', `${path}.${k}`, 'required field', undefined);
    for (const [k, v] of Object.entries(value)) {
      const s = schema.properties && Object.hasOwn(schema.properties,k) ? schema.properties[k] : (typeof schema.additionalProperties === 'object' ? schema.additionalProperties : null);
      if (s) assertShape(v, s, `${path}.${k}`);
      else if (schema.additionalProperties === false) issue('FIELD_UNKNOWN', `${path}.${k}`, Object.keys(schema.properties).join(', '), v);
    }
  }
}

// Offsets use JS UTF-16 string units. Each ref includes the immutable message id.
export function sourceCatalog(messages) {
  return messages.filter(m => m.role === 'user').flatMap(m => {
    const rows = [], pattern = /[^。；;！？!?\r\n]+[。；;！？!?]?|[。；;！？!?]/g;
    for (const match of m.content.matchAll(pattern)) {
      for (let offset = 0; offset < match[0].length; offset += 1000) {
        const start = match.index + offset, end = Math.min(match.index + match[0].length, start + 1000);
        if (m.content.slice(start, end).trim()) rows.push({ id: `source:${m.id}:${start}:${end}`, messageId: m.id, start, end, text: m.content.slice(start, end) });
      }
    }
    return rows;
  });
}
export const targetKeys = model => [...model.variables.map(v => 'variable:' + v.name), ...Object.keys(model.objective).map(k => 'objective:' + k), ...model.constraints.map(c => 'constraint:' + c.name)];
export function targetCatalog(model, gaps = []) {
  return [
    ...(model ? [
      ...model.variables.map(v => ({ id: 'variable:' + v.name, kind: 'variable', value: v, required: true })),
      { id: 'objective:$', kind: 'objective_direction', value: model.sense, required: true },
      ...Object.entries(model.objective).map(([name, coefficient]) => ({ id: 'objective:' + name, kind: 'objective_coefficient', value: coefficient, required: true })),
      ...model.constraints.map(c => ({ id: 'constraint:' + c.name, kind: 'constraint', value: c, required: true }))
    ] : []),
    { id: 'method:conditions', kind: 'applicability', required: false },
    ...gaps.map(g => ({ id: 'gap:' + g.id, kind: 'gap', factId: g.factId, required: false }))
  ];
}
export function diagnosticFor(error, stage) {
  return { ...(error.issue || { layer: error instanceof SyntaxError ? 'parse' : 'schema', code: error instanceof SyntaxError ? 'INVALID_JSON' : 'INVALID_SUBMISSION', path: '$', expected: error.message, received: null, recoverable: true }), stage };
}
export function diagnosticText(d, language = 'zh-CN') {
  const labels = language === 'en' ? { source: 'Source reference', reference: 'Object reference', schema: 'Submission fields', parse: 'JSON parsing', state: 'Evidence state', semantic: 'Semantic review', solver: 'Solver', numeric: 'Numerical validation', transport: 'Model request', budget: 'Request limit' }
    : { source: '原文引用', reference: '对象引用', schema: '提交字段', parse: 'JSON 解析', state: '证据状态', semantic: '语义审核', solver: '求解', numeric: '数值复核', transport: '模型请求', budget: '调用额度' };
  return language === 'en' ? `${labels[d.layer] || d.layer} failed at ${d.path}. ${d.code}. No unvalidated candidate was sent to the solver.`
    : `${labels[d.layer] || d.layer}未通过检查：${d.path}（${d.code}）。未将未验证的候选交给求解器。`;
}
