const params = new URLSearchParams(location.hash.slice(1));
if (params.has('token')) { sessionStorage.setItem('fyppppp-session', params.get('token')!); history.replaceState(null, '', location.pathname); }
export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api' + path, { method, signal, headers: { 'Content-Type': 'application/json', 'x-fyppppp-token': sessionStorage.getItem('fyppppp-session') || '' }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '操作失败');
  return value;
}
export async function streamChat(body: unknown, signal: AbortSignal, receive: (event: { type: string; text?: string; error?: string; conversation?: import('./types').Conversation }) => void) {
  const response = await fetch('/api/chat', { method: 'POST', signal, headers: { 'Content-Type': 'application/json', 'x-fyppppp-token': sessionStorage.getItem('fyppppp-session') || '' }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error((await response.json()).error || '发送失败');
  if (!response.body) throw new Error('连接中断');
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '', done = false;
  const line = (text: string) => { if (!text.trim()) return; const event = JSON.parse(text); if (event.type === 'error') throw new Error(event.error); if (event.type === 'done') done = true; receive(event); };
  try {
    for (;;) {
      const part = await reader.read(); buffer += decoder.decode(part.value, { stream: !part.done });
      let index; while ((index = buffer.indexOf('\n')) >= 0) { line(buffer.slice(0, index)); buffer = buffer.slice(index + 1); }
      if (part.done) break;
    }
    line(buffer); if (!done) throw new Error('连接中断，已收到的内容会保存在历史记录中');
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
