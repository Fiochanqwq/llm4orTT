import packageInfo from '../package.json';
import { Saturn } from './Saturn';
import { translator } from './i18n';
import { SolverSettings } from './Solver';
import { Calculator } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { X, Palette, KeyRound, Database, Check, ChevronDown, ArrowUpRight, Eye, EyeOff, RefreshCw, LoaderCircle, Download, Trash2, Minus, Plus } from 'lucide-react';
import { api, download } from './api';
import type { Language, ProviderSettings, Theme, Workspace } from './types';
export const themes: {
    id: Theme;
    name: string;
    colors: string[];
}[] = [
    { id: 'light', name: '浅白', colors: ['#f1f1f1', '#ffffff', '#252525'] },
    { id: 'graphite', name: '石墨灰', colors: ['#232323', '#2b2b2b', '#e4e4e4'] },
    { id: 'black', name: '纯黑', colors: ['#090909', '#151515', '#ececec'] },
    { id: 'navy', name: '深蓝白', colors: ['#172b48', '#ffffff', '#264e80'] }
];
export function Settings({ state, update, close, initialTab, initialProvider, notify, busy }: {
    state: Workspace;
    update: (state: Workspace) => void;
    close: () => void;
    initialTab: string;
    initialProvider: string;
    notify: (text: string) => void;
    busy: boolean;
}) {
    const t = translator(state.preferences.language);
    const [tab, setTab] = useState(initialTab), [selected, setSelected] = useState(initialProvider);
    const [form, setForm] = useState<ProviderSettings>(state.providers[selected]), [key, setKey] = useState(''), [visible, setVisible] = useState(false), [pending, setPending] = useState(''), [result, setResult] = useState(''), [advanced, setAdvanced] = useState(false), [confirmClear, setConfirmClear] = useState(false);
    const dialogRef = useRef<HTMLDivElement>(null);
    const pendingRef = useRef(pending);
    pendingRef.current = pending;
    const provider = state.catalog.find(p => p.id === selected)!;
    useEffect(() => { setForm(state.providers[selected]); setKey(''); setResult(''); setVisible(false); }, [selected]);
    useEffect(() => {
        const previous = document.activeElement as HTMLElement;
        dialogRef.current?.focus();
        function keyboard(e: KeyboardEvent) {
            if (e.key === 'Escape' && !pendingRef.current)
                close();
            if (e.key !== 'Tab')
                return;
            const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href],textarea:not([disabled]),[tabindex="0"]') || []).filter(x => x.getClientRects().length);
            if (!items.length)
                return;
            const first = items[0], last = items[items.length - 1];
            if (e.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
                e.preventDefault();
                last.focus();
            }
            else if (!e.shiftKey && (document.activeElement === last || document.activeElement === dialogRef.current)) {
                e.preventDefault();
                first.focus();
            }
        }
        document.addEventListener('keydown', keyboard);
        return () => { document.removeEventListener('keydown', keyboard); previous?.focus(); };
    }, [close]);
    async function setPreference(value: Partial<Workspace['preferences']>) {
        if (pending) return;
        setPending('preferences');
        try { update(await api<Workspace>('/preferences', 'PATCH', value)); }
        catch (error) { notify((error as Error).message); }
        finally { setPending(''); }
    }
    async function save(removeKey = false) {
        setPending('save');
        setResult('');
        try {
            const next = await api<Workspace>('/providers/' + selected, 'PUT', { ...form, apiKey: key, removeKey });
            update(next);
            setForm(next.providers[selected]);
            setKey('');
            setResult(removeKey ? t("密钥已移除") : t("已保存"));
            return next;
        }
        catch (error) {
            setResult((error as Error).message);
            return null;
        }
        finally {
            setPending('');
        }
    }
    async function connect(action: 'models' | 'test') {
        const saved = await save();
        if (!saved)
            return;
        if (!saved.providers[selected].hasKey) {
            setResult(t("请先填写 API 密钥"));
            return;
        }
        setPending(action);
        setResult('');
        try {
            const response = await api<{
                models?: string[];
                ok?: boolean;
                source?: string;
            }>('/providers/' + selected + '/' + action, 'POST', {});
            const next = await api<Workspace>('/state');
            update(next);
            setForm(next.providers[selected]);
            setResult(action === 'test' ? t("连接成功") : response.source === 'preset' ? t("当前使用官方模型预设") : t('已同步 {count} 个模型', { count: response.models?.length || 0 }));
        }
        catch (error) {
            setResult((error as Error).message);
        }
        finally {
            setPending('');
        }
    }
    async function exportData() {
        try {
            await download({conversationIds:state.conversations.map(c=>c.id),format:'json'});
        }
        catch (error) {
            notify((error as Error).message);
        }
    }
    const regionSpec = provider.regions.find(r => r.id === form.region);
    const modelOptions = [...new Set([...(regionSpec?.models || provider.models), ...(form.models || []), form.model])];
    return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && !pending)
        close(); }}><div ref={dialogRef} tabIndex={-1} className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
    <div className="settings-sidebar"><h2 id="settings-title">{t("设置")}</h2><nav>{[{ id: 'appearance', label: t("外观"), icon: Palette }, { id: 'api', label: 'API', icon: KeyRound }, { id: 'solver', label: state.preferences.language === 'en' ? 'Solver' : '求解器', icon: Calculator }, { id: 'data', label: t("数据"), icon: Database }].map(item => <button key={item.id} disabled={!!pending} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}><item.icon size={17}/>{item.label}</button>)}</nav><span className="version">llm4orOvO <span>{packageInfo.version}</span></span></div>
    <div className="settings-body"><button className="icon-button modal-close" title={t("关闭")} aria-label={t("关闭设置")} disabled={!!pending} onClick={close}><X size={19}/></button>
      {tab === 'appearance' && <><header className="settings-heading"><span className="eyebrow">APPEARANCE</span><h3>{t("外观")}</h3></header><div className="setting-row preference-row"><label htmlFor="interface-language">{t('语言')}</label><select id="interface-language" aria-label={t('语言')} value={state.preferences.language} disabled={!!pending} onChange={e => setPreference({ language: e.target.value as Language })}><option value="zh-CN">简体中文</option><option value="en">English</option></select></div>
      <div className="setting-row preference-row"><label htmlFor="reading-font">{state.preferences.language==='en'?'Reading font':'正文字体'}</label><select id="reading-font" value={state.preferences.readingFont} onChange={e=>setPreference({readingFont:e.target.value})}>{[['system',state.preferences.language==='en'?'System':'系统字体'],['calibri','Calibri'],['times','Times New Roman'],['arial','Arial'],['georgia','Georgia'],['verdana','Verdana']].map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></div>
      <div className="experiment-controls">{[[16,state.preferences.language==='en'?'Standard':'标准'],[18,state.preferences.language==='en'?'Comfortable':'舒适'],[20,state.preferences.language==='en'?'Large':'大字']].map(([size,label])=><button className="secondary-button" key={size} aria-pressed={state.preferences.fontSize===size} onClick={()=>setPreference({fontSize:Number(size)})}>{label}</button>)}</div><div className="setting-row preference-row"><label htmlFor="font-size">{t('字号')}</label><div className="font-size-controls"><button className="icon-button" aria-label={t('减小字号')} disabled={!!pending || state.preferences.fontSize <= 16} onClick={() => setPreference({ fontSize: state.preferences.fontSize - 1 })}><Minus size={16}/></button><select id="font-size" aria-label={t('字号')} disabled={!!pending} value={state.preferences.fontSize} onChange={e => setPreference({ fontSize: Number(e.target.value) })}>{[...new Set([state.preferences.fontSize,...Array.from({ length: 9 }, (_, index) => 16 + index)])].sort((a,b)=>a-b).map(size => <option key={size} value={size}>{size} px</option>)}</select><button className="icon-button" aria-label={t('增大字号')} disabled={!!pending || state.preferences.fontSize >= 24} onClick={() => setPreference({ fontSize: state.preferences.fontSize + 1 })}><Plus size={16}/></button><button className="text-button font-reset" disabled={!!pending || state.preferences.fontSize === 18} onClick={() => setPreference({ fontSize: 18 })}>{t('恢复默认')}</button></div></div><div className="field-heading appearance-theme-heading">{t("主题")}</div><div className="theme-grid">{themes.map(theme => <button key={theme.id} className={'theme-card ' + (state.preferences.theme === theme.id ? 'selected' : '')} disabled={!!pending} onClick={() => setPreference({ theme: theme.id })} aria-pressed={state.preferences.theme === theme.id}><div className="theme-preview" style={{ background: theme.colors[1] }}><div className="theme-mini-side" style={{ background: theme.colors[0] }}><i style={{ background: theme.colors[2] }}/><i style={{ background: theme.colors[2] }}/><i style={{ background: theme.colors[2] }}/></div><div className="theme-mini-main"><Saturn size={25}/><b style={{ borderColor: theme.colors[2] }}><i style={{ background: theme.colors[2] }}/></b></div></div><span className="theme-label">{t(theme.name)}{state.preferences.theme === theme.id && <Check size={15}/>}</span></button>)}</div><div className="setting-row"><span>{t("英文字体")}</span><span className="muted">{state.preferences.readingFont}</span></div><div className="setting-row"><span>{t("中文字体")}</span><span className="muted">{t("黑体")}</span></div></>}
      {tab === 'api' && <><header className="settings-heading"><span className="eyebrow">CONNECTIONS</span><h3>API</h3></header><div className="provider-tabs">{state.catalog.map(p => <button key={p.id} disabled={!!pending} className={selected === p.id ? 'selected' : ''} onClick={() => setSelected(p.id)}><span className={'provider-mark mark-' + p.id}>{p.mark}</span><span>{p.name}</span>{state.providers[p.id].hasKey && <span className="configured-dot"/>}</button>)}</div>
      <div className="provider-form"><div className="provider-form-heading"><h4>{provider.name}</h4><a href={regionSpec?.docs || provider.docs} target="_blank" rel="noreferrer">{t("文档")}<ArrowUpRight size={13}/></a></div>
        {provider.regions.length > 1 && <label className="field"><span>{t("地区")}</span><select aria-label={t("地区")} disabled={!!pending} value={form.region} onChange={e => setForm({ ...form, region: e.target.value, model: provider.regions.find(r => r.id === e.target.value)?.defaultModel || provider.defaultModel, models: [], baseURL: '' })}>{provider.regions.map(r => <option value={r.id} key={r.id}>{t(r.name)}</option>)}</select></label>}
        <label className="field"><span>{t("API 密钥 ")}<span className="field-status">{form.hasKey ? t("已保存") : t("未配置")}</span></span><div className="password-input"><input aria-label={t("API 密钥")} autoComplete="off" spellCheck={false} disabled={!!pending} type={visible ? 'text' : 'password'} value={key} onChange={e => setKey(e.target.value)} placeholder={form.hasKey ? '••••••••••••••••' : t("输入 API Key")}/><button type="button" className="icon-button" aria-label={visible ? t("隐藏密钥") : t("显示密钥")} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={16}/> : <Eye size={16}/>}</button></div></label>
        <label className="field"><span>{t("默认模型")}<button className="text-button" type="button" disabled={!!pending || (!form.hasKey && !key) || !provider.listModels} title={provider.listModels ? t("获取可用模型") : t("使用官方预设，可在高级设置自定义")} onClick={() => connect('models')}><RefreshCw size={12} className={pending === 'models' ? 'spin' : ''}/>{t("同步")}</button></span><select aria-label={t("默认模型")} value={form.model} disabled={!!pending} onChange={e => setForm({ ...form, model: e.target.value })}>{modelOptions.map(m => <option key={m} value={m}>{m}</option>)}</select></label>
        <button className="advanced-toggle" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>{t("高级设置")}<ChevronDown size={14} className={advanced ? 'rotate' : ''}/></button>
        {provider.id === 'deepseek' && <p className="test-note">{state.preferences.language === 'en' ? 'Official models: deepseek-flash and deepseek-v4-pro. The two legacy Flash names route to the current Flash model. Thinking mode is enabled; project output limits still apply.' : '官方模型：deepseek-flash、deepseek-v4-pro。两个旧 Flash 名称均转到当前 Flash，并非独立版本。使用思考模式，输出仍受本项目额度限制。'}</p>}
        {advanced && <div className="advanced-fields"><label className="field"><span>{t("接口地址")}</span><input disabled={!!pending} spellCheck={false} value={form.baseURL} placeholder={provider.regions.find(r => r.id === form.region)?.baseURL} onChange={e => setForm({ ...form, baseURL: e.target.value })}/></label><label className="field"><span>{t("自定义模型 ID")}</span><input value={form.model} disabled={!!pending} onChange={e => setForm({ ...form, model: e.target.value })}/></label><label className="field"><span>{t("输出上限")}</span><input type="number" min={256} max={327680} step={256} disabled={!!pending} value={form.maxTokens} onChange={e => setForm({ ...form, maxTokens: Number(e.target.value) })}/></label>{(['modelingTokens', 'explanationTokens'] as const).map(field => <label className="field" key={field}><span>{state.preferences.language === 'en' ? (field === 'modelingTokens' ? 'Modeling output limit' : 'Explanation output limit') : (field === 'modelingTokens' ? '建模输出上限' : '解读输出上限')}</span><input type="number" min={256} max={327680} step={256} disabled={!!pending} value={form[field]} onChange={e => setForm({ ...form, [field]: Number(e.target.value) })}/></label>)}<p className="test-note">{state.preferences.language === 'en' ? 'Stage limits also respect the overall output limit.' : '分阶段上限同时受总输出上限约束。'}</p>{form.hasKey && <button className="text-button danger-text" disabled={!!pending} onClick={() => save(true)}><Trash2 size={13}/>{t("移除密钥")}</button>}</div>}
        {result && <div className={'connection-result ' + (result === t("连接成功") || result === t("已保存") ? 'success' : '')} role="status">{result === t("连接成功") || result === t("已保存") ? <Check size={14}/> : null}{t(result)}</div>}
        <div className="form-actions"><button className="secondary-button" disabled={!!pending || (!form.hasKey && !key)} title={t("会发送一条简短请求，按厂商规则计费")} onClick={() => connect('test')}>{pending === 'test' && <LoaderCircle size={14} className="spin"/>}{t("测试连接")}</button><button className="primary-button" disabled={!!pending} onClick={() => save()}>{pending === 'save' && <LoaderCircle size={14} className="spin"/>}{t("保存")}</button></div><div className="test-note">{t("连接测试会发送一条简短 API 请求。")}</div>
      </div></>}
      {tab === 'solver' && <><header className="settings-heading"><span className="eyebrow">LOCAL</span><h3>{state.preferences.language === 'en' ? 'Solver' : '求解器'}</h3></header><SolverSettings language={state.preferences.language}/></>}
      {tab === 'data' && <><header className="settings-heading"><span className="eyebrow">WORKSPACE</span><h3>{t("数据")}</h3></header><div className="setting-row"><span>{t("本地对话")}</span><span className="muted">{state.conversations.length}</span></div><div className="data-action"><div><h4>{t("导出对话")}</h4><p>{t("JSON · 不含 API 密钥")}</p></div><button className="secondary-button" onClick={exportData}><Download size={15}/>{t("导出")}</button></div><div className="data-action"><div><h4>{t("清空对话")}</h4><p>{t("保留主题与 API 设置")}</p></div><button className="secondary-button danger-text" disabled={busy} onClick={() => setConfirmClear(true)}><Trash2 size={15}/>{t("清空")}</button></div>{confirmClear && <div className="confirm-inline"><span>{t('删除全部 {count} 个对话？', { count: state.conversations.length })}</span><button className="text-button" onClick={() => setConfirmClear(false)}>{t("取消")}</button><button className="danger-button" onClick={async () => { try {
        update(await api<Workspace>('/conversations', 'DELETE'));
        setConfirmClear(false);
    }
    catch (error) {
        notify((error as Error).message);
    } }}>{t("删除")}</button></div>}</>}
    </div>
  </div></div>;
}
