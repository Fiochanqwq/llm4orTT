// Actions are appended when taken, never reconstructed from final counters.
export const decisionMetricsVersion = 'controller-actions-2';
const actions = new Set(['repair', 'clarify', 'deliver', 'fallback']);
const repairKinds = new Set(['semantic', 'programmatic', 'tool']);
export function validDecisionEvents(events) {
  return Array.isArray(events) && events.every((event, index) => event &&
    event.sequence === index + 1 && actions.has(event.action) &&
    (event.action === 'repair' ? repairKinds.has(event.repairKind) : event.repairKind === null));
}
export function recordAction(task, action, reason, repairKind = null) {
  const events = task.decisionEvents ||= [];
  events.push({ sequence: events.length + 1, action, reason, repairKind,
    factVersion: task.factVersion ?? 0, calls: task.calls, solves: task.solves,
    clarifications: task.clarifications });
}
export function decisionMetrics(task) {
  if (task?.decisionMetricsVersion !== decisionMetricsVersion || !validDecisionEvents(task.decisionEvents)) {
    return { decisionMetricsVersion: null, firstDecision: null, decisionEvents: [],
      semanticRepairs: null, programmaticRepairs: null, toolRepairs: null };
  }
  const events = task.decisionEvents;
  const count = kind => events.filter(e => e.action === 'repair' && e.repairKind === kind).length;
  return { decisionMetricsVersion, firstDecision: events[0]?.action ?? null, decisionEvents: events,
    semanticRepairs: count('semantic'), programmaticRepairs: count('programmatic'), toolRepairs: count('tool') };
}
