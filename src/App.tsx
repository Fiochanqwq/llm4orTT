import packageInfo from '../package.json';
import { Solver } from './Solver';
import { ResearchCard } from './ResearchCard';
import { Experiments } from './Experiments';
import { methodPresets, methodLabel } from '../shared/methods.mjs';
import type { ReplyTo } from './types';
import { AutomationCard } from './AutomationCard';
import { validateModel } from '../shared/solver-model.mjs';
import { Calculator, Download } from 'lucide-react';
import { translator } from './i18n';
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, Square, Plus, Search, PanelLeftClose, PanelLeftOpen, Settings as SettingsIcon, ChevronDown, Check, MoreHorizontal, Pencil, Trash2, Copy, RotateCcw, Paperclip, X, ArrowDown, LoaderCircle, Sun, Moon, CircleAlert } from 'lucide-react';
import { api, streamChat, download } from './api';
import { Saturn } from './Saturn';
const Markdown = lazy(() => import('./Markdown').then(module => ({ default: module.Markdown })));
import { Settings, themes } from './Settings';
import type { Conversation, Message, Workspace } from './types';
export default function App() {
    const [solverReference, setSolverReference] = useState<string | null>(null), [requestedRunId, setRequestedRunId] = useState<string | null>(null);
    const [experimentsOpen,setExperimentsOpen]=useState(false);
    const sending=useRef(false);
    const [solverOpen, setSolverOpen] = useState(false), [solverImport, setSolverImport] = useState<string | null>(null);
    const [state, setState] = useState<Workspace | null>(null), [loadError, setLoadError] = useState('');
    const language = state?.preferences.language || 'zh-CN', t = translator(language);
    const [activeId, setActiveId] = useState<string | null>(sessionStorage.getItem('fyppppp-active'));
    const [query, setQuery] = useState(''), [draft, setDraft] = useState(''), [busy, setBusy] = useState(false), [toast, setToast] = useState('');
    const [narrow, setNarrow] = useState(window.innerWidth <= 580), [mobileOpen, setMobileOpen] = useState(false);
    const [settings, setSettings] = useState<{
        tab: string;
        provider: string;
    } | null>(null), [picker, setPicker] = useState(false), [menu, setMenu] = useState<string | null>(null);
    const [renaming, setRenaming] = useState<string | null>(null), [renameText, setRenameText] = useState(''), [deleting, setDeleting] = useState<string | null>(null), [copied, setCopied] = useState(''), [atBottom, setAtBottom] = useState(true);
    const textarea = useRef<HTMLTextAreaElement>(null), searchInput = useRef<HTMLInputElement>(null), fileInput = useRef<HTMLInputElement>(null), scroll = useRef<HTMLDivElement>(null), controller = useRef<AbortController | null>(null), toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const notify = useCallback((message: string) => { setToast(message); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 4500); }, []);
    const importModel = (text: string) => { try { const model = validateModel(JSON.parse(text)); setRequestedRunId(null); setSolverImport(JSON.stringify(model, null, 2)); setSolverOpen(true); setMobileOpen(false); } catch (error) { notify((error as Error).message); } };
    const closeSettings = useCallback(() => setSettings(null), []);
    const refresh = useCallback(async () => { try {
        setState(await api<Workspace>('/state'));
        setLoadError('');
    }
    catch (error) {
        setLoadError((error as Error).message);
    } }, []);
    useEffect(() => { refresh(); }, [refresh]);
    useEffect(() => { const media = window.matchMedia('(max-width: 580px)'); const resize = () => { setNarrow(media.matches); setMobileOpen(false); }; media.addEventListener('change', resize); return () => media.removeEventListener('change', resize); }, []);
    useEffect(() => { const focus = () => { if (!busy && !settings)
        refresh(); }; window.addEventListener('focus', focus); return () => window.removeEventListener('focus', focus); }, [refresh, busy, settings]);
    useEffect(() => { if (state)
        document.documentElement.dataset.theme = state.preferences.theme; }, [state?.preferences.theme]);
    useEffect(() => {
        document.documentElement.lang = language;
        document.documentElement.style.fontSize = (state?.preferences.fontSize || 18) + 'px';
        const fonts:Record<string,string>={system:'"Segoe UI", "Microsoft YaHei", sans-serif',calibri:'Calibri, "Microsoft YaHei", sans-serif',times:'"Times New Roman", "SimSun", serif',arial:'Arial, "Microsoft YaHei", sans-serif',georgia:'Georgia, "SimSun", serif',verdana:'Verdana, "Microsoft YaHei", sans-serif'};
        document.documentElement.style.setProperty('--reading-font',fonts[state?.preferences.readingFont||'system']||fonts.system);
        document.title = 'llm4orOvO';
    }, [language, state?.preferences.fontSize,state?.preferences.readingFont]);
    useEffect(() => { activeId ? sessionStorage.setItem('fyppppp-active', activeId) : sessionStorage.removeItem('fyppppp-active'); }, [activeId]);
    useEffect(() => { if (state && activeId && !state.conversations.some(c => c.id === activeId))
        setActiveId(null); }, [state, activeId]);
    useEffect(() => { if (textarea.current) {
        textarea.current.style.height = 'auto';
        textarea.current.style.height = Math.min(textarea.current.scrollHeight, 220) + 'px';
    } }, [draft]);
    const conversation = state?.conversations.find(c => c.id === activeId);
    const messages = conversation?.messages || [];
    useEffect(() => { if (atBottom && scroll.current)
        scroll.current.scrollTop = scroll.current.scrollHeight; }, [messages, atBottom]);
    useEffect(() => {
        function keyboard(e: KeyboardEvent) {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                searchInput.current?.focus();
            }
            if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'o' && !busy) {
                e.preventDefault();
                setActiveId(null);
                setDraft('');
                textarea.current?.focus();
            }
            if ((e.ctrlKey || e.metaKey) && e.key === ',') {
                e.preventDefault();
                setSettings({ tab: 'appearance', provider: state?.preferences.provider || 'openai' });
            }
            if (e.key === 'Escape') {
                setPicker(false);
                setMenu(null);
                setDeleting(null);
            }
        }
        window.addEventListener('keydown', keyboard);
        return () => window.removeEventListener('keydown', keyboard);
    }, [busy, state?.preferences.provider]);
    const updateConversation = (value: Conversation) => setState(current => current && { ...current, conversations: [value, ...current.conversations.filter(c => c.id !== value.id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)) });
    const providerId = state?.preferences.provider || 'openai';
    const provider = state?.catalog.find(p => p.id === providerId);
    const config = state?.providers[providerId];
    async function preferences(value: unknown) { try {
        setState(await api<Workspace>('/preferences', 'PATCH', value));
    }
    catch (error) {
        notify((error as Error).message);
    } }
    async function selectProvider(id: string) { await preferences({ provider: id }); }
    async function selectModel(model: string) {
        if (!config)
            return;
        try {
            setState(await api<Workspace>('/providers/' + providerId, 'PUT', { ...config, model }));
            setPicker(false);
        }
        catch (error) {
            notify((error as Error).message);
        }
    }
    async function send(retry = false, supplied?:string, replyTo?:ReplyTo) {
        if (!state || !config || busy || sending.current || (!retry && !(supplied??draft).trim()))
            return;
        if (!config.hasKey) {
            setSettings({ tab: 'api', provider: providerId });
            notify(t("填写 API 密钥后即可发送"));
            return;
        }
        const content = supplied??draft;
        let id = activeId, accepted = false;
        sending.current=true; setBusy(true);
        setAtBottom(true);
        controller.current = new AbortController();
        try {
            if (!id) {
                const next = await api<Conversation>('/conversations', 'POST', {});
                id = next.id;
                updateConversation(next);
                setActiveId(id);
            }
            if (!retry)
                setDraft('');
            await streamChat({ requestId:crypto.randomUUID(), replyTo, conversationId: id, message: content, provider: providerId, model: config.model, retry, mode: state.preferences.chatMode, engine: state.preferences.chatEngine, ...(!retry && solverReference ? { solverRunId: solverReference } : {}) }, controller.current.signal, event => {
                if (event.conversation) { updateConversation(event.conversation); if (event.type === 'start') { accepted = true; setSolverReference(null); } }
                else if (event.type === 'delta')
                    setState(current => current && { ...current, conversations: current.conversations.map(c => c.id === id ? { ...c, messages: c.messages.map((m, i) => i === c.messages.length - 1 ? { ...m, content: m.content + (event.text || '') } : m) } : c) });
            });
        }
        catch (error) {
            if ((error as Error).name !== 'AbortError') {
                notify((error as Error).message);
                if (!retry && !accepted)
                    setDraft(content);
            }
        }
        finally {
            sending.current=false; setBusy(false);
            controller.current = null;
            setTimeout(() => refresh(), 300);
            textarea.current?.focus();
        }
    }
    async function rename(id: string) { if (!renameText.trim()) {
        setRenaming(null);
        return;
    } try {
        updateConversation(await api<Conversation>('/conversations/' + id, 'PATCH', { title: renameText }));
        setRenaming(null);
    }
    catch (error) {
        notify((error as Error).message);
    } }
    async function remove(id: string) { try {
        await api('/conversations/' + id, 'DELETE');
        setDeleting(null);
        if (id === activeId) {
            setActiveId(null);
            setDraft('');
        }
        await refresh();
    }
    catch (error) {
        notify((error as Error).message);
    } }
    async function copy(message: Message) { try {
        await navigator.clipboard.writeText(message.content);
        setCopied(message.id);
        setTimeout(() => setCopied(''), 1500);
    }
    catch {
        notify(t("复制失败，请手动选择文本"));
    } }
    async function exportConversation(id: string) {
        setMenu(null);
        try {
            await download({conversationIds:[id],format:'json'});
        } catch (error) { notify((error as Error).message); }
    }
    const collapsed = narrow ? !mobileOpen : state?.preferences.sidebarCollapsed || false;
    function toggleSidebar(close = false) { if (narrow)
        setMobileOpen(!close);
    else
        preferences({ sidebarCollapsed: close }); }
    const filtered = state?.conversations.filter(c => !query || (c.title + ' ' + c.messages.map(m => m.content).join(' ')).toLowerCase().includes(query.toLowerCase())) || [];
    function composer() {
        return <div className="composer-wrap"><div className={'composer ' + (busy ? 'is-busy' : '')}>
      {solverReference && <div className="solver-context-chip"><Calculator size={14}/><span>{language === "en" ? "Attached solver record" : "已附求解记录"} · {solverReference.slice(0, 8)}</span><button className="icon-button" aria-label={language === "en" ? "Remove solver record" : "移除求解记录"} onClick={() => setSolverReference(null)}><X size={13}/></button></div>}
      <textarea ref={textarea} aria-label={t("消息")} placeholder={t("描述你的问题…")} rows={2} value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            send();
        } }} maxLength={60000}/>
      <div className="method-preset"><label>{language==='en'?'Method (new task)':'方法（新任务）'}<select disabled={busy} value={state?.preferences.methodPreset||'full'} onChange={e=>preferences({methodPreset:e.target.value})}>{Object.keys(methodPresets).map(id=><option key={id} value={id}>{methodLabel(id,language)}</option>)}</select></label><label className="protocol-option"><input type="checkbox" disabled={busy} checked={state?.preferences.protocolCorrection!==false} onChange={e=>preferences({protocolCorrection:e.target.checked})}/>{language==='en'?'Allow one submission correction (within 4 calls)':'允许一次提交纠正（计入 4 次调用）'}</label>{conversation?.messages.slice().reverse().find(m=>m.automation?.task?.frozen)?.automation?.task?.frozen&&<span>{language==='en'?'Current task is frozen':'当前任务使用冻结配置'}</span>}</div><div className="composer-toolbar"><div className="composer-tools"><button className="icon-button attachment-button" title={t("附加文本文件")} aria-label={t("附加文本文件")} disabled={busy} onClick={() => fileInput.current?.click()}><Paperclip size={19}/></button><span className="composer-divider"/><button className="composer-model" disabled={busy} onClick={() => setPicker(!picker)}>{provider?.name}<ChevronDown size={12}/></button><select className="composer-mode" aria-label={language === 'en' ? 'Chat mode' : '对话模式'} disabled={busy || !!solverReference} value={state?.preferences.chatMode || 'solve'} onChange={e => preferences({ chatMode: e.target.value })}><option value="solve">{language === 'en' ? 'Auto solve' : '自动求解'}</option><option value="chat">{language === 'en' ? 'Chat' : '对话'}</option></select>{state?.preferences.chatMode === 'solve' && !solverReference && <select className="composer-engine" aria-label={language === 'en' ? 'Solver engine' : '求解引擎'} disabled={busy} value={state.preferences.chatEngine} onChange={e => preferences({ chatEngine: e.target.value })}><option value="highs">HiGHS</option><option value="gurobi">Gurobi</option></select>}</div>
      <button className={'send-button ' + (busy ? 'stop-button' : '')} disabled={!busy && !draft.trim()} aria-label={busy ? t("停止生成") : t("发送消息")} title={busy ? t("停止生成") : t("发送消息")} onClick={() => busy ? controller.current?.abort() : send()}>{busy ? <Square size={15} fill="currentColor"/> : <ArrowUp size={21}/>}</button></div>
    </div></div>;
    }
    if (!state)
        return <div className="loading-screen"><Saturn size={76}/>{loadError ? <><p>{t(loadError)}</p><button className="secondary-button" onClick={refresh}>{t("重试")}</button></> : <LoaderCircle className="spin" size={19}/>}</div>;
    return <div className={'app-shell ' + (collapsed ? 'sidebar-collapsed' : '')}>
    {narrow && mobileOpen && <button className="mobile-sidebar-overlay" aria-label={t("关闭侧栏")} onClick={() => setMobileOpen(false)}/>}
    <aside className="sidebar"><div className="brand-row"><a className="brand" href="#" onClick={e => { e.preventDefault(); if (!busy) {
        setActiveId(null);
        setDraft('');
    } }}><Saturn size={35}/><span>llm4orOvO</span></a><button className="icon-button collapse-button" title={t("收起侧栏")} aria-label={t("收起侧栏")} onClick={() => toggleSidebar(true)}><PanelLeftClose size={18}/></button></div>
      <button className="new-chat" disabled={busy} onClick={() => { setSolverReference(null); setExperimentsOpen(false); setSolverOpen(false); setActiveId(null); setDraft(''); textarea.current?.focus(); }}><Plus size={18}/><span>{t("新对话")}</span><kbd>Ctrl ⇧ O</kbd></button>
      <button className={'solver-entry settings-entry ' + (solverOpen ? 'active' : '')} onClick={() => { setExperimentsOpen(false); setSolverOpen(!solverOpen); setMobileOpen(false); }}><Calculator size={18}/><span>{language === 'en' ? 'Solver' : '求解器'}</span></button>
      <button className={'settings-entry '+(experimentsOpen?'active':'')} onClick={()=>{setExperimentsOpen(true);setSolverOpen(false);setMobileOpen(false);}}><Calculator size={18}/>{language==='en'?'Experiments':'实验工作台'}</button>
      <div className="search-field"><Search size={15}/><input ref={searchInput} aria-label={t("搜索对话")} placeholder={t("搜索对话")} value={query} onChange={e => setQuery(e.target.value)}/>{query ? <button className="icon-button" aria-label={t("清除搜索")} onClick={() => setQuery('')}><X size={12}/></button> : <kbd>Ctrl K</kbd>}</div>
      <div className="history-heading">{t("对话")}<span>{state.conversations.length.toString().padStart(2, '0')}</span></div>
      <nav className="conversation-list" aria-label={t("对话记录")}>{filtered.length === 0 ? <div className="empty-history">{query ? t("没有匹配的对话") : t("暂无对话")}</div> : filtered.map(c => <div className={'conversation-row ' + (c.id === activeId ? 'active' : '')} key={c.id}>
        {renaming === c.id ? <input className="rename-input" aria-label={t("对话名称")} autoFocus value={renameText} onChange={e => setRenameText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter')
            rename(c.id); if (e.key === 'Escape')
            setRenaming(null); }} onBlur={() => rename(c.id)}/> : <><button className="conversation-title" disabled={busy} onClick={() => { setSolverReference(null); setExperimentsOpen(false); setSolverOpen(false); setActiveId(c.id); setDraft(''); setAtBottom(true); }} title={c.title}>{c.title}</button><button className="icon-button conversation-menu" disabled={busy} aria-label={t("管理 ") + c.title} onClick={() => setMenu(menu === c.id ? null : c.id)}><MoreHorizontal size={16}/></button></>}
        {menu === c.id && <><div className="dismiss-layer" onClick={() => setMenu(null)}/><div className="row-menu"><button disabled={busy} onClick={() => exportConversation(c.id)}><Download size={14}/>{t("导出为 JSON")}</button><button onClick={() => { setRenaming(c.id); setRenameText(c.title); setMenu(null); }}><Pencil size={14}/>{t("重命名")}</button><button className="danger-text" onClick={() => { setDeleting(c.id); setMenu(null); }}><Trash2 size={14}/>{t("删除")}</button></div></>}
      </div>)}</nav>
      <div className="sidebar-footer"><button className="settings-entry" aria-label={t("设置")} onClick={() => setSettings({ tab: 'appearance', provider: providerId })}><SettingsIcon size={18}/><span>{t("设置")}</span><span className="settings-key">Ctrl ,</span></button><div className="workspace-foot"><span className="local-dot"/>{t("本地工作区")}<span>v{packageInfo.version}</span></div></div>
    </aside>
    <main className="main-panel"><header className="topbar"><div className="topbar-left">{collapsed && <button className="icon-button" title={t("展开侧栏")} aria-label={t("展开侧栏")} onClick={() => toggleSidebar()}><PanelLeftOpen size={19}/></button>}<div className="model-anchor"><button className={'model-trigger ' + (picker ? 'open' : '')} disabled={busy} onClick={() => setPicker(!picker)} aria-expanded={picker}><span>{config?.model}</span><ChevronDown size={15}/></button>
      {picker && <><div className="dismiss-layer" onClick={() => setPicker(false)}/><div className="model-popover"><div className="model-provider-list">{state.catalog.map(p => <button className={p.id === providerId ? 'selected' : ''} key={p.id} onClick={() => selectProvider(p.id)}><span className="provider-mark">{p.mark}</span>{p.name}{state.providers[p.id].hasKey && <span className="configured-dot"/>}</button>)}</div><div className="model-options"><div className="popover-heading">{t("模型")}</div>{[...new Set([...(provider?.regions.find(r => r.id === config?.region)?.models || provider?.models || []), ...(config?.models || []), config?.model || ''])].filter(Boolean).map(model => <button className={model === config?.model ? 'selected' : ''} key={model} onClick={() => selectModel(model)}><span>{model}</span>{model === config?.model && <Check size={14}/>}</button>)}<button className="configure-models" onClick={() => { setSettings({ tab: 'api', provider: providerId }); setPicker(false); }}><SettingsIcon size={14}/>{t("配置 API")}</button></div></div></>}
    </div></div><div className="topbar-right">{conversation && !solverOpen && <button className="icon-button" disabled={busy} title={t("导出当前对话为 JSON")} aria-label={t("导出当前对话为 JSON")} onClick={() => exportConversation(conversation.id)}><Download size={18}/></button>}{collapsed && <button className="icon-button" aria-label={language === 'en' ? 'Solver' : '求解器'} onClick={() => setSolverOpen(!solverOpen)}><Calculator size={18}/></button>}<span className="connection-state"><span className={config?.hasKey ? 'connected' : ''}/>{config?.hasKey ? t("已配置") : t("未配置")}</span><span className="header-divider"/><button className="icon-button" title={t("切换主题")} aria-label={t("切换主题")} onClick={() => { const next = themes[(themes.findIndex(t => t.id === state.preferences.theme) + 1) % themes.length]; preferences({ theme: next.id }); }}>{state.preferences.theme === 'light' || state.preferences.theme === 'navy' ? <Sun size={18}/> : <Moon size={18}/>}</button></div></header>
    {(state.storageError || state.recovery || !!state.skippedRecords) && <div className="recovery-notice" role="status">
      {state.storageError ? (language === 'en' ? 'Saving is unavailable. New tasks are paused. Check disk space and file permissions, then restart the app. The latest changes may not have been saved.' : '记录暂时无法保存，已暂停新任务。请检查磁盘空间和文件权限后重新启动；最近的操作可能尚未保存。') : state.recovery ? (state.recovery.restoredFromBackup ? (language === 'en' ? 'The workspace was restored from its previous saved backup. Please check recent conversations. Any damaged original file has been preserved.' : '工作区已从上一份保存备份恢复，请核对最近的对话。损坏的原文件已保留。') : (language === 'en' ? 'A damaged workspace was preserved separately. No valid backup was found, so an empty workspace is open.' : '损坏的工作区文件已单独保留；没有找到有效备份，当前打开的是空白工作区。')) : null}
      {!!state.skippedRecords && <span>{language === 'en' ? ` ${state.skippedRecords} unreadable history records were skipped; their files remain available for recovery.` : ` 有 ${state.skippedRecords} 条历史记录暂时无法读取，原文件仍保留供恢复。`}</span>}
    </div>}
    {experimentsOpen ? <Experiments state={state} notify={notify}/> : solverOpen ? <Solver language={language} imported={solverImport} requestedRunId={requestedRunId} configure={() => setSettings({ tab: 'solver', provider: providerId })} toChat={(text, runId) => { setSolverReference(runId || null); setSolverOpen(false); setDraft(text); setTimeout(() => textarea.current?.focus(), 0); }}/> : messages.length === 0 ? <div className="empty-workspace"><div className="welcome"><div className="welcome-mark"><Saturn size={94}/></div><h1>{t("新对话")}</h1></div>{composer()}</div> : <><div className="message-scroll" ref={scroll} onScroll={() => { if (scroll.current)
            setAtBottom(scroll.current.scrollHeight - scroll.current.scrollTop - scroll.current.clientHeight < 110); }}><div className="message-column">{messages.map((message, index) => <article className={'message message-' + message.role} key={message.id}>
      {message.role === 'assistant' && <div className="message-meta"><Saturn size={26}/><span>{state.catalog.find(p => p.id === message.provider)?.name || t("助手")}</span><span className="message-model">{message.model}</span></div>}
      {message.role === 'user' ? <div className="user-bubble">{message.content}</div> : <>{message.automation?.methods && message.automation.methods.preset !== 'legacy' ? <ResearchCard flow={message.automation} language={language} streaming={message.status==='streaming'} active={index===messages.length-1} busy={busy} reply={(text,to)=>void send(false,text,to)} open={id=>{setRequestedRunId(id);setSolverOpen(true);}}/> : message.automation && <AutomationCard flow={message.automation} language={language} streaming={message.status === "streaming"} open={id => { setSolverImport(null); setRequestedRunId(id); setSolverOpen(true); }}/>}<div className="message-provenance" data-source={message.provenance?.solverRun ? "llm-solver-interpretation" : "llm"}><span>{message.automation ? (language === "en" ? "Auto solve" : "自动求解") : message.provenance?.solverRun ? (language === "en" ? "AI interpretation" : "模型解读") : (language === "en" ? "AI response · no local solver call" : "模型回复 · 未调用本地求解器")}</span>{message.provenance?.solverRun && <button onClick={() => { setSolverImport(null); setRequestedRunId(message.provenance!.solverRun!.id); setSolverOpen(true); }}><Calculator size={13}/>{language === "en" ? "View solver record" : "查看真实求解记录"} · {message.provenance.solverRun.id.slice(0, 8)}</button>}</div><div className="answer-content">{message.content && message.content !== message.automation?.decision?.summary ? <Suspense fallback={<div>{message.content}</div>}><Markdown text={message.content} language={language} onModel={importModel}/></Suspense> : message.status === 'streaming' ? <span className="thinking-dots" aria-label={t("正在生成")}><i /><i /><i /></span> : null}</div>{message.error && <div className="message-status" role="status">{message.status === 'error' && <CircleAlert size={14}/>}<span>{t(message.error)}</span></div>}{message.warning && <div className="message-status">{t(message.warning)}</div>}</>}
      {message.status !== 'streaming' && <div className="message-actions">{message.content && <button className="icon-button" title={t("复制")} aria-label={t("复制消息")} onClick={() => copy(message)}>{copied === message.id ? <Check size={14}/> : <Copy size={14}/>}</button>}{message.role === 'assistant' && (!message.automation || message.automation.task?.technicalFailure) && index === messages.length - 1 && <button className="icon-button" title={t("重新生成")} aria-label={t("重新生成")} disabled={busy} onClick={() => send(true)}><RotateCcw size={14}/></button>}{message.role === 'assistant' && message.usage && (message.usage.input !== null || message.usage.output !== null) && <span className="usage">{message.usage.input ?? '—'} / {message.usage.output ?? '—'} tokens</span>}</div>}
    </article>)}</div></div><div className="composer-dock">{!atBottom && <button className="scroll-bottom" title={t("滚动到底部")} aria-label={t("滚动到底部")} onClick={() => { setAtBottom(true); scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' }); }}><ArrowDown size={17}/></button>}{composer()}</div></>}
    </main>
    <input type="file" ref={fileInput} className="hidden" accept=".txt,.md,.csv,.json,.py" onChange={async (e) => { const file = e.target.files?.[0]; e.target.value = ''; if (!file)
        return; if (file.size > 150000) {
        notify(t("文本文件需小于 150 KB"));
        return;
    } const text = await file.text(); const next = draft + '\n\n' + file.name + '\n```\n' + text + '\n```'; if (next.length > 60000) {
        notify(t("总内容超过 60000 字符"));
        return;
    } setDraft(next.trimStart()); textarea.current?.focus(); }}/>
    {settings && <Settings state={state} update={setState} close={closeSettings} initialTab={settings.tab} initialProvider={settings.provider} notify={notify} busy={busy}/>}
    {deleting && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget)
        setDeleting(null); }}><div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title"><h3 id="delete-title">{t("删除此对话？")}</h3><p>{state.conversations.find(c => c.id === deleting)?.title}</p><div className="form-actions"><button className="secondary-button" autoFocus onClick={() => setDeleting(null)}>{t("取消")}</button><button className="danger-button" onClick={() => remove(deleting)}>{t("删除")}</button></div></div></div>}
    {toast && <div className="toast" role="status">{t(toast)}<button className="icon-button" aria-label={t("关闭提示")} onClick={() => setToast('')}><X size={14}/></button></div>}
  </div>;
}
