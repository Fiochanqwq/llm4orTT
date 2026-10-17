// Shared by chat and experiment requests; rejected requests release their slot.
const abortReason = signal => signal?.reason instanceof Error ? signal.reason : new DOMException('Aborted', 'AbortError');
// Waiting for a slot must itself be cancellable: otherwise an aborted request keeps its conversation
// marked as generating until whatever is running ahead of it finishes.
export function waitAbortable(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortReason(signal));
  let onAbort;
  const gate = new Promise((_, reject) => { onAbort = () => reject(abortReason(signal)); signal.addEventListener('abort', onAbort, { once: true }); });
  return Promise.race([promise, gate]).finally(() => signal.removeEventListener('abort', onAbort));
}
// An aborted waiter still hands its slot on only after the run ahead of it finishes, so the FIFO order
// survives the cancellation.
export function createModelQueue(){let tail=Promise.resolve();return async function run(fn,signal){const before=tail;let release;tail=new Promise(r=>{release=r;});let acquired=false;try{await waitAbortable(before,signal);signal?.throwIfAborted();acquired=true;return await fn();}finally{if(acquired)release();else before.then(release,release);}};}
