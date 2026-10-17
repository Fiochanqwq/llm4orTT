// Necessary conditions only: two linear scans, no candidate enumeration or model repair.
// The caller must first validate llm4orovo.lp.v1. Passing is not a semantic certificate.
export function preflightModel(model) {
  const tolerance = (...xs) => 1e-8 * Math.max(1, ...xs.filter(Number.isFinite).map(Math.abs));
  const bounds = new Map(model.variables.map(v => [v.name, { lower: v.lower ?? -Infinity, upper: v.upper ?? Infinity, type: v.type, lowerSource: v.name + ': lower/domain', upperSource: v.name + ': upper/domain' }]));
  const describe = sources => sources.slice(0, 12).join(', ') + (sources.length > 12 ? `, … (+${sources.length - 12})` : '');
  const evidence = [], conflicts=[];
  for (const c of model.constraints) {
    const entries = Object.entries(c.terms).filter(([, a]) => a !== 0);
    if (entries.length !== 1) continue;
    const [name, a] = entries[0], b = bounds.get(name), value = c.rhs / a;
    if (!Number.isFinite(value)) continue;
    const direction = a < 0 ? ({ '<=': '>=', '>=': '<=', '=': '=' })[c.sense] : c.sense;
    if (direction !== '<=' && value > b.lower) { b.lower = value; b.lowerSource = c.name; }
    if (direction !== '>=' && value < b.upper) { b.upper = value; b.upperSource = c.name; }
  }
  for (const [name, b] of bounds) {
    if (b.type !== 'continuous') { b.lower = Math.ceil(b.lower - tolerance(b.lower)); b.upper = Math.floor(b.upper + tolerance(b.upper)); }
    if (b.lower > b.upper + tolerance(b.lower, b.upper)) {evidence.push(`${name}: lower ${b.lower} > upper ${b.upper}; ${b.type}; ${b.lowerSource}, ${b.upperSource}`);conflicts.push({kind:'bounds',variable:name,lower:b.lower,upper:b.upper,type:b.type,sources:[b.lowerSource,b.upperSource]});}
  }
  // Inconsistent bounds already suffice; do not present a reversed interval as attainable.
  if (evidence.length) return { status: 'conflict', method: 'bounds_and_single_variable_constraints', evidence: evidence.slice(0, 3), conflicts:conflicts.slice(0,3) };
  for (const c of model.constraints) {
    let min = 0, max = 0;
    for (const [name, a] of Object.entries(c.terms)) {
      if (a === 0) continue;
      const b = bounds.get(name); min += a * (a > 0 ? b.lower : b.upper); max += a * (a > 0 ? b.upper : b.lower);
    }
    const eps = tolerance(min, max, c.rhs);
    if ((c.sense !== '>=' && min > c.rhs + eps) || (c.sense !== '<=' && max < c.rhs - eps)) {
      const sources = [...new Set(Object.keys(c.terms).filter(k => c.terms[k] !== 0).flatMap(k => [bounds.get(k).lowerSource, bounds.get(k).upperSource]))];
      evidence.push(`${c.name}: attainable [${min}, ${max}], required ${c.sense} ${c.rhs}; ${describe(sources)}`);
      conflicts.push({kind:'constraint_range',constraint:c.name,terms:{...c.terms},min,max,sense:c.sense,rhs:c.rhs,sources});
    }
    if (evidence.length >= 3) break;
  }
  return { status: evidence.length ? 'conflict' : 'no_obvious_conflict', method: 'bounds_and_single_variable_constraints', evidence: evidence.slice(0, 3), conflicts:conflicts.slice(0,3) };
}
