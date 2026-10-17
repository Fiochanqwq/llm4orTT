import { exactCertificate, compareExact } from '../shared/exact-certificate.mjs';
import { numericalCheck } from '../shared/result-contract.mjs';
export function budgetDecision(record, budget) {
  if(!budget||!Number.isFinite(budget.lower)||!Number.isFinite(budget.upper)||budget.lower>budget.upper)return {status:'uncertain',reason:'invalid_budget_interval'};
  if(!record.provenance?.solverInvoked || record.model?.sense!=='minimize')return {status:'uncertain',reason:'no_minimization_evidence'};
  if(record.status==='infeasible')return {status:'all_infeasible',reason:'base_model_infeasible'};
  if(!['optimal','time_limit'].includes(record.status))return {status:'uncertain',reason:'no_finite_cost_evidence'};
  const check=numericalCheck(record.model,record.values);
  const exact=exactCertificate(record.model,record.values);
  if(exact){
    if(compareExact(exact.objective,budget.lower)<=0)return {status:'all_feasible',exact};
    if(compareExact(exact.objective,budget.upper)>0)return {status:'all_infeasible',exact};
    return {status:'needs_clarification',threshold:check?.objective,exact};
  }
  const upper=check?.feasible&&Number.isFinite(check.objective)?check.objective:null;
  const lower=Number.isFinite(record.bound)?record.bound:null;
  const scale=Math.max(1,Math.abs(upper??0),Math.abs(lower??0),Math.abs(budget.upper)), margin=1e-7*scale;
  // Floating-point values close to the threshold require stronger evidence.
  if(upper!==null && upper<budget.lower-margin)return {status:'all_feasible',upper,lower};
  if(lower!==null && lower>budget.upper+margin)return {status:'all_infeasible',upper,lower};
  if(record.status==='optimal' && upper!==null && lower!==null && Math.abs(upper-lower)<=margin && upper>budget.lower+margin && upper<budget.upper-margin)return {status:'needs_clarification',threshold:upper,upper,lower};
  return {status:'uncertain',upper,lower,reason:'boundary_or_incomplete_certificate'};
}

export function resolveBudgetReply(pending, reply) {
  const t=reply.normalize('NFKC').trim();
  // Parse a whole, unambiguous amount statement, never a number extracted from
  // hypothetical text or a message that also changes model conditions.
  const revised=/^(?:更正|修正|更新|修改|correction\s*[:：]?)/i.test(t);
  const body=t.replace(/^(?:更正|修正|更新|修改|correction\s*[:：]?)\s*/i,'')
    .replace(/^(?:已批准且不可追加的预算|已批准且固定的预算|已批准预算|实际预算|预算|(?:the\s+)?(?:approved fixed budget|fixed approved budget|approved budget|actual budget|budget))\s*(?:就是|改为|为|是|is|[:：])?\s*/i,'')
    .replace(/[,，;；]\s*(?:不能追加|不可追加|不可增加|no additions|it cannot be increased)[。.!]?$/i,'').replace(/[。.!]$/,'').trim();
  const unit='(?:美元|美金|人民币元?|元|欧元|英镑|日元|USD|CNY|RMB|EUR|GBP|JPY|CAD|AUD|HKD|SGD|CHF|US dollars?|dollars?)';
  const number='(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?';
  const amount=body.match(new RegExp(`^(${unit})?\\s*(${number})\\s*(${unit})?$`,'i'));
  if(amount){
    // Bare amounts inherit the current question's unit. An explicit currency
    // must match it; comparing different currencies requires new evidence.
    const canonicalUnit=unit=>{const u=String(unit||'').normalize('NFKC').trim().toLowerCase();if(['usd','美元','美金','us dollar','us dollars','dollar','dollars'].includes(u))return 'usd';if(['cny','rmb','人民币','人民币元','元'].includes(u))return 'cny';return ({欧元:'eur',英镑:'gbp',日元:'jpy'})[u]||u;};
    const conflicting=[amount[1],amount[3]].find(u=>u&&canonicalUnit(u)!==canonicalUnit(pending.budget.unit));
    if(conflicting)return revised?{status:'revision'}:{status:'unit_conflict',expectedUnit:pending.budget.unit,receivedUnit:conflicting};
    const value=Number(amount[2].replaceAll(',',''));if(!Number.isFinite(value))return {status:'unparsed'};
    if(value<pending.budget.lower||value>pending.budget.upper)return {status:revised?'revision':'conflict'};return {status:'amount',value};
  }
  if(pending.exact && /^(是|是的|yes|y)[。.!]?$/i.test(t))return {status:'side',side:true};
  if(pending.exact && /^(否|不是|no|n)[。.!]?$/i.test(t))return {status:'side',side:false};
  return {status:'unparsed'};
}
