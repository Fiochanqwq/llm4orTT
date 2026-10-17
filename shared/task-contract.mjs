import { protocolVersion, reviewVersion, contractSchema, reviewSchema, assertShape, sourceCatalog, targetCatalog, targetKeys, issue } from './protocol-schema.mjs';
export { targetKeys, sourceCatalog, targetCatalog } from './protocol-schema.mjs';
const text = (x, max = 1000) => typeof x === 'string' && x.length > 0 && x.length <= max;
const array = (x, max = 1000) => Array.isArray(x) && x.length <= max;
const known = (ids, map, path, layer = 'reference') => {
  if (!array(ids, 2000) || ids.some(id => !map.has(id))) issue('UNKNOWN_REFERENCE', path, [...map.keys()].join(', ').slice(0, 5000), ids, { layer });
};
const object = (value, keys, path) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) issue('FIELD_TYPE', path, 'object', value);
  const extra = Object.keys(value).filter(k => !keys.includes(k));
  if (extra.length) issue('FIELD_UNKNOWN', path, keys.join(', '), extra);
};
function anchor(value, messages, catalog, path, modern) {
  if (modern) {
    const map = new Map(catalog.map(s => [s.id, s]));
    if (!array(value.sourceRefs, 16) || !value.sourceRefs.length) issue('SOURCE_REQUIRED', path + '.sourceRefs', '1..16 source ids', value.sourceRefs, { layer: 'source' });
    known(value.sourceRefs, map, path + '.sourceRefs', 'source');
    const evidence = [...new Set(value.sourceRefs)].map(id => map.get(id));
    return { sourceRefs: evidence.map(s => s.id), sourceEvidence: evidence, sourceMessageId: evidence[0].messageId, sourceSpan: evidence.map(s => s.text).join('\n') };
  }
  const m = messages.find(m => m.id === value.sourceMessageId && m.role === 'user');
  if (!text(value.sourceSpan, 3000) || !m?.content.includes(value.sourceSpan)) issue('SOURCE_NOT_LITERAL', path + '.sourceSpan', 'a literal contiguous excerpt, or sourceRefs from sourceCatalog in v3', value.sourceSpan, { layer: 'source' });
  const start = m.content.indexOf(value.sourceSpan), end = start + value.sourceSpan.length;
  return { sourceMessageId: m.id, sourceSpan: value.sourceSpan, sourceEvidence: [{ messageId: m.id, start, end, text: value.sourceSpan }] };
}

export function validateContract(raw, messages, model = null, { budgetEnabled = true } = {}) {
  const modern = raw?.format === protocolVersion, value = structuredClone(raw), catalog = sourceCatalog(messages);
  if (modern) assertShape(value, contractSchema);
  else {
    object(value, ['format', 'modelPurpose', 'facts', 'bindings', 'gaps', 'budget'], '$');
    if (value.format !== 'llm4orovo.submission.v2' || !['final_task', 'budget_threshold_base'].includes(value.modelPurpose) || !array(value.facts) || !array(value.bindings, 1500) || !array(value.gaps, 50)) issue('CONTRACT_SCHEMA', '$', protocolVersion, value?.format);
  }
  const facts = new Map();
  value.facts = value.facts.map((f, i) => {
    const p = `$.facts[${i}]`;
    if (!modern) {
      object(f, ['id', 'kind', 'sourceMessageId', 'sourceSpan', 'entityRefs', 'unit', 'value', 'status', 'supersedes'], p);
      if (!['active', 'superseded', 'unresolved'].includes(f.status) || !array(f.entityRefs, 200) || f.entityRefs.some(x => !text(x, 80))) issue('FACT_SCHEMA', p, 'legacy fact fields', f);
    }
    if (!text(f.id, 80) || facts.has(f.id) || !text(f.kind, 80) || !array(f.supersedes, 100) || f.supersedes.some(x => !text(x, 80)) || typeof f.unit !== 'string' || f.unit.length > 80) issue('FACT_SCHEMA', p, 'unique fact id, kind, unit, supersedes', f);
    if (!(f.value === null || typeof f.value === 'boolean' || typeof f.value === 'string' && f.value.length <= 1000 || Number.isFinite(f.value) && Math.abs(f.value) <= 1e9 || modern && f.value && typeof f.value === 'object' && Number.isFinite(f.value.lower) && f.value.lower <= f.value.upper)) issue('FACT_VALUE', p + '.value', 'scalar or ordered finite interval', f.value);
    const result = { ...f, ...anchor(f, messages, catalog, p, modern), status: modern ? 'active' : f.status };
    facts.set(f.id, result); return result;
  });
  const latestEvidenceIndex = f => Math.max(-1,...(f?.sourceEvidence || []).map(s=>messages.findIndex(m=>m.id===s.messageId)));
  for (const f of facts.values()) for (const id of f.supersedes) {
    const old = facts.get(id);
    if (!old || latestEvidenceIndex(old) >= latestEvidenceIndex(f)) issue('INVALID_SUPERSESSION', '$.facts.' + f.id, 'replacement evidence from a newer user message', id, { layer: 'state' });
    old.status = 'superseded';
  }
  for (const f of facts.values()) if (f.status === 'superseded' && !value.facts.some(n => n.supersedes.includes(f.id))) issue('MISSING_REPLACEMENT', '$.facts.' + f.id, 'a newer superseding fact', f.id, { layer: 'state' });
  const gaps = new Map();
  value.gaps = value.gaps.map((g, i) => {
    const p = `$.gaps[${i}]`;
    if (!modern) object(g, ['id', 'factId', 'kind', 'status', 'questionId'], p);
    if (!text(g.id, 80) || gaps.has(g.id) || !facts.has(g.factId) || facts.get(g.factId).status === 'superseded' || !text(g.kind, 80)) issue('INVALID_GAP', p, 'unique gap with an active fact', g, { layer: 'reference' });
    // Execution states are never accepted on trust from a model, including v2.
    if (!modern && (!['open', 'uncertain'].includes(g.status) || g.questionId !== null)) issue('UNVERIFIED_GAP_STATE', p + '.status', 'open or uncertain; the application owns resolved/asked/proven_irrelevant', g.status, { layer: 'state' });
    const result = { ...g, status: 'open', questionId: null }; gaps.set(g.id, result); return result;
  });
  for(const f of facts.values())if(f.status==='unresolved'&&!value.gaps.some(g=>g.factId===f.id))issue('UNRESOLVED_FACT_WITHOUT_GAP','$.facts.'+f.id,'an explicit gap for an unresolved fact',f.id,{layer:'state'});
  const targets = new Map(targetCatalog(model, value.gaps).map(t => [t.id, t])), covered = new Set(), handled = new Set();
  value.bindings = value.bindings.map((b, i) => {
    const p = `$.bindings[${i}]`;
    if (!modern) {
      object(b, ['factIds', 'targetKind', 'targetIds', 'disposition'], p);
      if (!['variable', 'objective', 'constraint', 'gap'].includes(b.targetKind) || !array(b.targetIds)) issue('BINDING_SCHEMA', p, 'known target kind and targetIds', b);
    }
    if (!array(b.factIds, 100) || !b.factIds.length || !['encoded', 'pending_clarification', 'deferred_to_budget_gate', 'not_applicable'].includes(b.disposition)) issue('BINDING_SCHEMA', p, 'nonempty facts and valid disposition', b);
    known(b.factIds, facts, p + '.factIds');
    if (b.factIds.some(id => facts.get(id).status === 'superseded')) issue('SUPERSEDED_BINDING', p + '.factIds', 'active facts only', b.factIds, { layer: 'state' });
    const refs = modern ? b.targetRefs : b.targetIds.map(id => b.targetKind + ':' + id);
    known(refs, targets, p + '.targetRefs');
    if (!refs.length) issue('BINDING_TARGET_REQUIRED', p + '.targetRefs', 'an explicit valid target; method:conditions for applicability', refs, { layer: 'reference' });
    if (b.disposition === 'encoded') {
      if (refs.some(id => !targets.get(id).required)) issue('ENCODED_TARGET', p, 'mathematical targets only', refs, { layer: 'reference' });
      refs.forEach(id => covered.add(id));
    } else if (b.disposition === 'not_applicable') {
      if (!modern || refs.some(id => id !== 'method:conditions') || !b.reason.trim()) issue('APPLICABILITY_REASON', p, 'v3 method:conditions and an explicit anchored reason; does not count as mathematical coverage', b, { layer: 'reference' });
    } else {
      if (refs.some(id => targets.get(id).kind !== 'gap' || !b.factIds.includes(targets.get(id).factId))) issue('GAP_BINDING', p, 'gap refs bound to their own fact', refs, { layer: 'reference' });
      if (b.disposition === 'deferred_to_budget_gate' && (refs.length !== 1 || refs[0] !== 'gap:' + value.budget?.gapId || !b.factIds.includes(value.budget?.factId))) issue('BUDGET_BINDING', p, 'the registered budget fact and gap', refs, { layer: 'reference' });
    }
    b.factIds.forEach(id => handled.add(id));
    return { ...b, targetRefs: refs };
  });
  const required = model ? (modern ? targetCatalog(model).filter(t => t.required).map(t => t.id) : targetKeys(model)) : [];
  if (model && required.some(id => !covered.has(id))) issue('MODEL_COVERAGE', '$.bindings', 'encoded bindings for ' + required.filter(id => !covered.has(id)).join(', '), [...covered], { layer: 'reference' });
  if (value.facts.some(f => f.status !== 'superseded' && !handled.has(f.id))) issue('FACT_COVERAGE', '$.bindings', 'disposition for every active fact', value.facts.filter(f => f.status !== 'superseded' && !handled.has(f.id)).map(f => f.id), { layer: 'reference' });
  if (value.modelPurpose === 'budget_threshold_base') {
    const b = value.budget;
    object(b, ['factId', 'gapId', 'lower', 'upper', 'unit', 'costTerms', 'confirmedFixed', 'onlyCostCap', 'otherConditionsComplete'], '$.budget');
    if (!budgetEnabled || !model || model.sense !== 'minimize' || !facts.has(b.factId) || !gaps.has(b.gapId) || !Number.isFinite(b.lower) || !Number.isFinite(b.upper) || b.lower < 0 || b.lower > b.upper || b.upper > 1e9 || !text(b.unit, 80) || b.confirmedFixed !== true || b.onlyCostCap !== true || b.otherConditionsComplete !== true) issue('BUDGET_PRECONDITIONS', '$.budget', 'fixed independent cost cap with a known interval and complete other facts', b);
    if (!b.costTerms || Object.keys(b.costTerms).length !== Object.keys(model.objective).length || Object.entries(model.objective).some(([k, v]) => b.costTerms[k] !== v)) issue('BUDGET_EXPRESSION', '$.budget.costTerms', 'exactly the submitted minimization objective', b.costTerms);
    if (value.gaps.some(g => g.id !== b.gapId) || gaps.get(b.gapId).factId !== b.factId || !value.bindings.some(x => x.disposition === 'deferred_to_budget_gate' && x.factIds.includes(b.factId))) issue('BUDGET_GAPS', '$.gaps', 'only the registered, explicitly deferred budget gap', value.gaps);
  } else if (value.budget !== null) issue('BUDGET_PURPOSE', '$.budget', 'null for final_task', value.budget);
  value.coverage = { kind: 'reference_coverage_not_semantic_proof', coarseFacts: value.facts.length === 1 && !!model && required.length > 3, encodedTargets: [...covered] };
  return value;
}

export function parseSubmission(plan, provider, toolName) {
  if (!plan || plan.truncated) issue('INCOMPLETE_SUBMISSION', '$', 'one complete response', null, { layer: 'parse', recoverable: false });
  let raw, source;
  if (plan.calls?.length === 1 && plan.calls[0].name === toolName) { raw = plan.calls[0].arguments; source = 'native_tool'; }
  else if (provider === 'deepseek' && Array.isArray(plan.calls) && plan.calls.length === 0 && typeof plan.text === 'string' && plan.text.length <= 250000) {
    const t = plan.text.trim(), fenced = t.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i); raw = fenced ? fenced[1] : t; source = 'json_content';
  } else issue('SUBMISSION_ENVELOPE', '$', 'exactly one ' + toolName + ' call', null, { layer: 'parse' });
  const value = typeof raw === 'string' ? JSON.parse(raw) : raw;
  if (!value || typeof value !== 'object' || Array.isArray(value)) issue('SUBMISSION_OBJECT', '$', 'object', value, { layer: 'parse' });
  return { value, source };
}

export function validateReview(raw, contract, messages, model) {
  const modern = raw?.format === reviewVersion, value = structuredClone(raw), normalizations = [];
  if (modern) assertShape(value, reviewSchema);
  else {
    object(value, ['status', 'diagnostics', 'factIds', 'targetIds', 'budgetApplicability'], '$');
    if (!['no_issue_found', 'mismatch', 'uncertain'].includes(value.status) || !array(value.diagnostics, 100) || !array(value.factIds) || !array(value.targetIds, 1500) || !['supported', 'unsupported', 'uncertain', 'not_applicable'].includes(value.budgetApplicability)) issue('REVIEW_SCHEMA', '$', reviewVersion, value);
    value.gapIds = [];
  }
  const facts = new Map(contract.facts.map(f => [f.id, f])), gaps = new Map(contract.gaps.map(g => [g.id, g])), targets = new Map(targetCatalog(model).map(t => [t.id, t]));
  const refs = (item, path) => {
    if (!modern) {
      item.gapIds ||= [];
      // Moving a known, explicitly typed gap reference is lossless. Never drop it.
      item.targetIds = item.targetIds.filter(id => {
        if (typeof id === 'string' && id.startsWith('gap:') && gaps.has(id.slice(4))) {
          item.gapIds.push(id.slice(4)); normalizations.push({ path: path + '.targetIds', from: id, to: { gapId: id.slice(4) }, rule: 'typed_gap_reference' }); return false;
        }
        return true;
      });
    }
    known(item.factIds, facts, path + '.factIds'); known(item.targetIds, targets, path + '.targetIds'); known(item.gapIds, gaps, path + '.gapIds');
  };
  refs(value, '$');
  const catalog = sourceCatalog(messages);
  value.diagnostics = value.diagnostics.map((d, i) => {
    const p = `$.diagnostics[${i}]`;
    if (!modern) object(d, ['code', 'factIds', 'targetIds', 'sourceMessageId', 'sourceSpan', 'evidence', 'repairable'], p);
    if (!text(d.code, 80) || !array(d.factIds) || !array(d.targetIds) || !text(d.evidence) || typeof d.repairable !== 'boolean') issue('DIAGNOSTIC_SCHEMA', p, 'anchored structured diagnostic', d);
    refs(d, p); return { ...d, ...anchor(d, messages, catalog, p, modern) };
  });
  if (value.status === 'mismatch' && !value.diagnostics.length) issue('DIAGNOSIS_REQUIRED', '$.diagnostics', 'at least one mismatch diagnosis', []);
  if (value.status === 'no_issue_found' && value.diagnostics.length) issue('REVIEW_CONFLICT', '$.status', 'mismatch or uncertain when diagnoses exist', value.status);
  const required = modern ? targetCatalog(model).filter(t => t.required).map(t => t.id) : targetKeys(model);
  const missing = { facts: contract.facts.filter(f => f.status !== 'superseded' && !value.factIds.includes(f.id)).map(f => f.id), targets: required.filter(id => !value.targetIds.includes(id)), gaps: modern ? contract.gaps.filter(g => !value.gapIds.includes(g.id)).map(g => g.id) : [] };
  if (Object.values(missing).some(a => a.length)) return { ...value, status: 'uncertain', coverageIncomplete: true, missingCoverage: missing, normalizations };
  return { ...value, normalizations };
}
