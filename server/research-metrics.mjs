export function trajectoryState(run) {
  const flow = run.conversation?.messages.findLast(m => m.automation)?.automation;
  if (!flow) return run.preset === 'native_api' || run.mock ? 'complete' : 'partial';
  if (flow.stage === 'clarification') return 'awaiting_human';
  if (flow.stage === 'unsupported') return 'unsupported';
  if (['paused', 'stopped'].includes(flow.stage)) return 'partial';
  if (['error', 'failed'].includes(flow.stage) || flow.failure) return 'failed';
  return flow.stage === 'complete' ? 'complete' : 'partial';
}

export function summarizeRuns(runs) {
  const groups = new Map();
  for (const r of runs) {
    const key = r.preset + '|' + r.baseId;
    if (!groups.has(key)) groups.set(key, { preset: r.preset, baseId: r.baseId, total: 0, attempted: 0, completed: 0, failed: 0, partial: 0, scored: 0, correct: 0, incorrect: 0, unscored: 0, unknownCompletionScore: 0, calls: 0, clarifications: 0, protocolCorrections: 0, protocolFailures: {} });
    const g = groups.get(key); g.total++;
    const attempted = r.attempted === true || !!r.score || ['running', 'complete', 'failed', 'partial', 'unsupported', 'awaiting_human', 'interrupted_unknown'].includes(r.status);
    if (!attempted) continue;
    g.attempted++;
    const complete = r.status === 'complete';
    if (complete) g.completed++;
    if (['failed', 'interrupted_unknown', 'cancelled'].includes(r.status)) g.failed++;
    if (['partial', 'unsupported', 'awaiting_human'].includes(r.status)) g.partial++;
    const verdict=r.manualVerdict??r.score?.independent?.verdict;
    const scored = ['correct', 'incorrect'].includes(verdict);
    if (scored) g.scored++; else g.unscored++;
    if (verdict === 'incorrect') g.incorrect++;
    // A positive manual label cannot turn an unfinished attempt into success.
    if (complete && verdict === 'correct') g.correct++;
    if (complete && !scored) g.unknownCompletionScore++;
    g.calls += r.score?.calls || 0; g.clarifications += r.score?.clarifications || 0;
    g.protocolCorrections += r.score?.protocolCorrections || 0;
    if (r.failure?.code) g.protocolFailures[r.failure.code] = (g.protocolFailures[r.failure.code] || 0) + 1;
  }
  const clusters = [...groups.values()].map(g => ({ ...g, correctRate: g.scored ? g.correct / g.scored : null,
    taskSuccessLower: g.attempted ? g.correct / g.attempted : null,
    taskSuccessUpper: g.attempted ? (g.correct + g.unknownCompletionScore) / g.attempted : null }));
  const methods = [...new Set(clusters.map(g => g.preset))].map(preset => {
    const gs = clusters.filter(g => g.preset === preset), attempted = gs.filter(g => g.attempted), scored = gs.filter(g => g.scored);
    const sum = field => gs.reduce((n, g) => n + g[field], 0), mean = (rows, key) => rows.length ? rows.reduce((n, g) => n + g[key], 0) / rows.length : null;
    return { preset, baseProblems: gs.length, attemptedBaseProblems: attempted.length, scoredBaseProblems: scored.length,
      meanBaseCorrectRate: mean(scored, 'correctRate'), meanBaseTaskSuccessLower: mean(attempted, 'taskSuccessLower'), meanBaseTaskSuccessUpper: mean(attempted, 'taskSuccessUpper'),
      totalTrajectories: sum('total'), attempted: sum('attempted'), completed: sum('completed'), failed: sum('failed'), partial: sum('partial'), scored: sum('scored'), correct: sum('correct'), incorrect: sum('incorrect'), unscored: sum('unscored'), calls: sum('calls'), protocolCorrections: sum('protocolCorrections') };
  });
  return { version: 'base-cluster-summary-2', inference: 'descriptive_only', denominator: 'all_attempted_tasks; unfinished attempts are not successful; ungraded completed tasks form the upper bound', methods, clusters };
}
