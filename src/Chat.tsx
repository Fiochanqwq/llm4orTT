import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Square, Plus, Search, Copy, RotateCcw, Download, Pencil, Trash2, Paperclip, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { api, streamChat } from './api';
import { Markdown } from './Markdown';
import type { Conversation, Workspace } from './types';
import './chat.css';

export function Chat({ state, update, settings }: { state: Workspace; update: (state: Workspace) => void; settings: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([]), [active, setActive] = useState<string | null>(sessionStorage.getItem('normal-chat-active'));
  const [draft, setDraft] = useState(sessionStorage.getItem('normal-chat-draft') || ''), [query, setQuery] = useState(''), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [busyId, setBusyId] = useState<string | null>(null), [pending, setPending] = useState(false), [notice, setNotice] = useState('');
  const [sidebar, setSidebar] = useState(window.innerWidth > 700), [rename, setRename] = useState<string | null>(null), [title, setTitle] = useState(''), [deleting, setDeleting] = useState(false);
  const sending = useRef(false), controller = useRef<AbortController | null>(null), input = useRef<HTMLTextAreaElement>(null), files = useRef<HTMLInputElement>(null), scroll = useRef<HTMLDivElement>(null), follow = useRef(true);
  const selected = conversations.find(c => c.id === active), current = state.providers[state.preferences.provider];
  const refresh = async () => { const values = await api<Conversation[]>('/conversations'); setConversations(values); };
  const receive = (c: Conversation) => setConversations(values => [c, ...values.filter(v => v.id !== c.id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
  useEffect(() => { refresh().catch(e => setError(e.message)); return () => controller.current?.abort(); }, []);
  useEffect(() => { active ? sessionStorage.setItem('normal-chat-active', active) : sessionStorage.removeItem('normal-chat-active'); setRename(null); setDeleting(false); }, [active]);
  useEffect(() => { sessionStorage.setItem('normal-chat-draft', draft); }, [draft]);
  useEffect(() => { if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [selected?.messages]);
  useEffect(() => { if (notice) { const timer = setTimeout(() => setNotice(''), 2500); return () => clearTimeout(timer); } }, [notice]);
  const choose = (id: string | null) => { setActive(id); setError(''); follow.current = true; if (window.innerWidth <= 700) setSidebar(false); input.current?.focus(); };
  async function send(retry = false) {
    if (sending.current || (!retry && !draft.trim())) return;
    if (!current.hasKey) { settings(); setError('先在设置里填写 API Key，就可以正常聊天。'); return; }
    sending.current = true; setBusy(true); setError(''); follow.current = true;
    const text = draft; let accepted = false, id = active;
    controller.current = new AbortController();
    try {
      if (!selected) { const next = await api<Conversation>('/conversations', 'POST', {}); id = next.id; receive(next); setActive(id); }
      setBusyId(id);
      await streamChat({ conversationId: id, message: text, retry, requestId: crypto.randomUUID(), provider: state.preferences.provider }, controller.current.signal, event => {
        if (event.conversation) { receive(event.conversation); if (event.type === 'start') { accepted = true; if (!retry) setDraft(''); } }
        else if (event.type === 'delta') setConversations(values => values.map(c => c.id === id ? { ...c, messages: c.messages.map((m, i) => i === c.messages.length - 1 ? { ...m, content: m.content + (event.text || '') } : m) } : c));
      });
    } catch (e) { if ((e as Error).name !== 'AbortError') setError((e as Error).message); if (!accepted && !retry) setDraft(text); }
    finally { sending.current = false; controller.current = null; setBusy(false); setBusyId(null); await refresh().catch(e => setError(e.message)); input.current?.focus(); }
  }
  async function stop() { if (busyId) { try { await api('/conversations/' + busyId + '/stop', 'POST', {}); } catch { controller.current?.abort(); } } }
  async function changeTitle() {
    if (!selected || pending) return; setPending(true);
    try { receive(await api<Conversation>('/conversations/' + selected.id, 'PATCH', { title })); setRename(null); }
    catch (e) { setError((e as Error).message); } finally { setPending(false); }
  }
  async function remove() {
    if (!selected || pending) return; setPending(true);
    try { await api('/conversations/' + selected.id, 'DELETE'); setConversations(values => values.filter(c => c.id !== selected.id)); choose(null); setDeleting(false); }
    catch (e) { setError((e as Error).message); } finally { setPending(false); }
  }
  function download() {
    if (!selected) return; const blob = new Blob([JSON.stringify(selected, null, 2)], { type: 'application/json' }), url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = selected.title.replace(/[<>:"/\\|?*]/g, '_').slice(0, 60) + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  async function attach(file?: File) {
    if (!file) return;
    try { if (file.size > 200000 || !/\.(txt|md|json|csv|py|js|ts|log)$/i.test(file.name)) throw new Error('请选择 200 KB 以内的文本文件'); const text = await file.text(); if (text.includes('\0')) throw new Error('这个文件不是普通文本'); setDraft(value => value + '\n\n附件：' + file.name + '\n' + text); }
    catch (e) { setError((e as Error).message); }
    finally { if (files.current) files.current.value = ''; }
  }
  return <section className={'chat-shell' + (sidebar ? ' with-sidebar' : '')} aria-label="普通对话">
    {sidebar && <><button className="chat-scrim" aria-label="关闭历史列表" onClick={() => setSidebar(false)}/><aside className="chat-sidebar">
      <div className="chat-side-actions"><button onClick={() => { choose(null); setDraft(''); }} disabled={busy}><Plus size={18}/>新建对话</button><button aria-label="收起历史列表" onClick={() => setSidebar(false)}><PanelLeftClose size={18}/></button></div>
      <label className="chat-search"><Search size={16}/><input aria-label="搜索历史对话" placeholder="搜索历史对话" value={query} onChange={e => setQuery(e.target.value)}/></label>
      <nav aria-label="聊天记录">{conversations.filter(c => (c.title + c.messages.map(m => m.content).join(' ')).toLowerCase().includes(query.toLowerCase())).map(c => <button key={c.id} className={c.id === active ? 'active' : ''} onClick={() => choose(c.id)} title={c.title}>{c.title}{busyId === c.id && <small>生成中</small>}</button>)}{!conversations.length && <p>聊过的内容会保存在这里。</p>}</nav>
    </aside></>}
    <div className="chat-main">
      <header className="chat-toolbar">{!sidebar && <button aria-label="展开历史列表" onClick={() => setSidebar(true)}><PanelLeftOpen size={19}/></button>}<span className="chat-title">{selected?.title || '新对话'}</span><div className="chat-toolbar-actions">
        <select aria-label="聊天服务商" value={state.preferences.provider} disabled={busy} onChange={async e => { try { update(await api<Workspace>('/preferences', 'PATCH', { provider: e.target.value })); } catch (e) { setError((e as Error).message); } }}>{state.catalog.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        {selected && <><button aria-label="重命名对话" disabled={pending} onClick={() => { setRename(selected.id); setTitle(selected.title); setDeleting(false); }}><Pencil size={16}/></button><button aria-label="导出对话" onClick={download}><Download size={17}/></button><button aria-label="删除对话" disabled={busyId === selected.id || pending} onClick={() => { setDeleting(true); setRename(null); }}><Trash2 size={16}/></button></>}
      </div></header>
      {rename === selected?.id && <form className="chat-inline" onSubmit={e => { e.preventDefault(); changeTitle(); }}><input autoFocus aria-label="对话标题" maxLength={200} value={title} onChange={e => setTitle(e.target.value)}/><button disabled={pending || !title.trim()}>保存标题</button><button type="button" onClick={() => setRename(null)}>取消</button></form>}
      {deleting && <div className="chat-inline" role="alert"><span>删除这段对话？</span><button onClick={remove} disabled={pending}>确认删除</button><button onClick={() => setDeleting(false)}>取消</button></div>}
      <div className="chat-messages" ref={scroll} onScroll={() => { const el = scroll.current!; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100; }}>
        {!selected?.messages.length && <div className="chat-welcome"><img src="/saturn-icon.png" alt=""/><h1>今天想聊些什么？</h1><p>问问题、写东西、聊想法，都可以。</p></div>}
        {selected?.messages.map((m, index) => <article key={m.id} className={'chat-message ' + m.role}><div className="chat-message-label">{m.role === 'user' ? '你' : m.model || '助手'}</div>{m.role === 'user' ? <div className="chat-user-text">{m.content}</div> : <Markdown text={m.content || (m.status === 'streaming' ? '正在思考…' : '')}/>}{m.error && <p className="chat-message-error">{m.error}</p>}{m.warning && <p className="chat-message-error">{m.warning}</p>}<div className="chat-message-actions"><button aria-label="复制消息" onClick={async () => { try { await navigator.clipboard.writeText(m.content); setNotice('已复制'); } catch { setError('复制失败，请选择文字复制'); } }}><Copy size={14}/>复制</button>{m.role === 'assistant' && index === selected.messages.length - 1 && <button disabled={busy} onClick={() => send(true)}><RotateCcw size={14}/>重新生成</button>}</div></article>)}
      </div>
      <div className="chat-composer-area">{error && <div role="alert" className="solver-error">{error}</div>}{notice && <div role="status" className="chat-notice">{notice}</div>}
        <form className="chat-composer" onSubmit={e => { e.preventDefault(); send(); }}><textarea ref={input} aria-label="输入消息" placeholder="输入消息，Enter 发送，Shift+Enter 换行" value={draft} disabled={busy} maxLength={100000} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/><div className="chat-composer-tools"><button type="button" disabled={busy} aria-label="添加文本文件" onClick={() => files.current?.click()}><Paperclip size={18}/></button><input ref={files} type="file" hidden accept=".txt,.md,.json,.csv,.py,.js,.ts,.log" onChange={e => attach(e.target.files?.[0])}/><span>{current.model}</span>{busy ? <button type="button" className="chat-send" aria-label="停止生成" onClick={stop}><Square size={17}/></button> : <button className="chat-send" type="submit" aria-label="发送消息" disabled={!draft.trim()}><ArrowUp size={20}/></button>}</div></form>
        <small className="chat-footnote">{current.hasKey ? '回复由所选模型生成，重要信息请核实。' : <button onClick={settings}>设置模型与 API Key 后即可发送</button>}</small>
      </div>
    </div>
  </section>;
}
