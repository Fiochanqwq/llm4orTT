// All automatic callers share one FIFO; manual runs occupy the same SolverService.
const tails = new WeakMap();
import { waitAbortable } from './model-queue.mjs';
export async function queuedSolve(solver, data, signal, started) {
  const previous = tails.get(solver) || Promise.resolve();
  let release; const mine = new Promise(r => { release = r; }); tails.set(solver, mine);
  let acquired = false;
  try {
    await waitAbortable(previous, signal);
    acquired = true;
    while (solver.active) { signal.throwIfAborted(); await new Promise(r => setTimeout(r, 50)); }
    signal.throwIfAborted();
    const record = solver.start(data); started(record);
    const cancel = () => solver.stop(record.id); signal.addEventListener('abort', cancel, { once: true });
    try { while (record.status === 'running') { if (signal.aborted) cancel(); await new Promise(r => setTimeout(r, 50)); } }
    finally { signal.removeEventListener('abort', cancel); }
    return record;
  } finally {
    const finish = () => { release(); if (tails.get(solver) === mine) tails.delete(solver); };
    if (acquired) finish(); else previous.then(finish, finish);
  }
}
