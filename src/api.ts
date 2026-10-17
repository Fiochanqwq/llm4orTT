import type { StreamEvent } from './types';
const params = new URLSearchParams(location.hash.slice(1));
if (params.has('token')) { sessionStorage.setItem('fyppppp-session', params.get('token')!); history.replaceState(null, '', location.pathname); }
const headers = () => ({ 'Content-Type': 'application/json', 'x-fyppppp-token': sessionStorage.getItem('fyppppp-session') || '' });
export async function download(selection:unknown){const value=await api<{url:string;filename:string}>('/downloads','POST',selection);const link=document.createElement('a');link.href=value.url;link.download=value.filename;document.body.appendChild(link);link.click();link.remove();}
export async function importArchive(file:File){if(file.size>64*1024*1024)throw Error('Archive limit: 64 MB');if(file.name.toLowerCase().endsWith('.zip')){const response=await fetch('/api/imports/zip',{method:'POST',headers:{'x-fyppppp-token':sessionStorage.getItem('fyppppp-session')||'','content-type':'application/zip'},body:file});const value=await response.json();if(!response.ok)throw Error(value.error);return value;}const text=await file.text();return api('/imports','POST',file.name.toLowerCase().endsWith('.jsonl')?{format:'llm4orovo.summary.v2',rows:text.trim().split(/\r?\n/).map(line=>JSON.parse(line))}:JSON.parse(text));}
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, { method, headers: headers(), ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '操作失败');
  return value;
}
export async function streamChat(body: unknown, signal: AbortSignal, receive: (event: StreamEvent) => void) {
  const response = await fetch('/api/chat', { method: 'POST', headers: headers(), body: JSON.stringify(body), signal });
  if (!response.ok) { const value = await response.json(); throw new Error(value.error || '无法发送消息'); }
  if (!response.body) throw new Error('当前环境不支持流式输出');
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '', finished = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const part = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        if (part.startsWith('data: ')) { const event: StreamEvent = JSON.parse(part.slice(6)); if (event.type === 'done') finished = true; receive(event); }
      }
    }
    if (!finished) throw new Error('连接已中断，已生成的内容已保留');
  } finally { reader.releaseLock(); }
}
