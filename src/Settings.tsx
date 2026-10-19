import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { api } from './api';
import type { Workspace } from './types';

export function Settings({ state, update, close }: { state: Workspace; update: (s: Workspace) => void; close: () => void }) {
  const [selected, setSelected] = useState(state.preferences.provider);
  const [form, setForm] = useState(state.providers[selected]), [key, setKey] = useState(''), [pending, setPending] = useState(false), [message, setMessage] = useState('');
  const dialog = useRef<HTMLDivElement>(null);
  const provider = state.catalog.find(p => p.id === selected)!;
  useEffect(() => { setForm(state.providers[selected]); setKey(''); setMessage(''); }, [selected]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    dialog.current?.focus();
    return () => previous?.focus();
  }, []);
  const save = async (test = false, removeKey = false) => {
    setPending(true); setMessage('');
    try {
      await api<Workspace>('/providers/' + selected, 'PUT', { ...form, apiKey: key, removeKey });
      const next = await api<Workspace>('/preferences', 'PATCH', { provider: selected });
      update(next); setForm(next.providers[selected]); setKey('');
      if (test) await api('/providers/' + selected + '/test', 'POST', {});
      setMessage(test ? '连接成功' : removeKey ? '密钥已移除' : '已保存');
    } catch (e) { setMessage((e as Error).message); }
    finally { setPending(false); }
  };
  const refreshModels = async () => {
    setPending(true); setMessage('');
    try {
      await api<Workspace>('/providers/' + selected, 'PUT', { ...form, apiKey: key });
      const result = await api<{ models: string[] }>('/providers/' + selected + '/models', 'POST', {});
      const next = await api<Workspace>('/state');
      update(next); setForm(next.providers[selected]); setKey('');
      setMessage('已获取 ' + result.models.length + ' 个可用模型');
    } catch (e) { setMessage((e as Error).message); }
    finally { setPending(false); }
  };
  return <div className="modal-backdrop"><div className="settings-dialog" role="dialog" aria-modal="true" aria-label="设置" tabIndex={-1} ref={dialog} onKeyDown={e => {
    if (e.key === 'Escape' && !pending) close();
    if (e.key === 'Tab') {
      const items = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary') || []).filter(el => el.getClientRects().length);
      const first = items[0], last = items.at(-1);
      if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
  }}>
    <header><h2>设置</h2><button aria-label="关闭设置" disabled={pending} onClick={close}><X size={20}/></button></header>
    <label>模型服务商<select value={selected} disabled={pending} onChange={e => setSelected(e.target.value)}>{state.catalog.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <label>地区<select value={form.region} disabled={pending} onChange={e => setForm({ ...form, region: e.target.value })}>{provider.regions.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
    <label>模型<input value={form.model} list="provider-models" disabled={pending} onChange={e => setForm({ ...form, model: e.target.value })}/><datalist id="provider-models">{[...new Set([...(provider.models || []), ...(provider.regions.find(r => r.id === form.region)?.models || []), ...form.models])].map(m => <option key={m} value={m}/>)}</datalist></label>
    <label>API Key<input type="password" autoComplete="off" value={key} disabled={pending} placeholder={form.hasKey ? '已保存，留空保留' : '填写 API Key'} onChange={e => setKey(e.target.value)}/></label>
    {selected === 'deepseek' && <p className="inverse-note">支持新旧模型 ID。旧版或自部署模型可在高级设置中填写兼容接口地址；可用版本以该接口提供的模型为准。</p>}
    <button disabled={pending || (!key && !form.hasKey)} onClick={refreshModels}>刷新可用模型</button>
    <details><summary>高级设置</summary><label>接口地址<input value={form.baseURL} placeholder="使用服务商默认地址" disabled={pending} onChange={e => setForm({ ...form, baseURL: e.target.value })}/></label><label>输出长度上限<input type="number" min={256} max={393216} value={form.maxTokens} disabled={pending} onChange={e => setForm({ ...form, maxTokens: Number(e.target.value) })}/></label></details>
    <div className="settings-buttons"><button disabled={pending} className="primary-button" onClick={() => save()}>保存</button><button disabled={pending || (!key && !form.hasKey)} onClick={() => save(true)}>测试连接</button>{form.hasKey && <button disabled={pending} onClick={() => save(false, true)}>移除密钥</button>}</div>
    <p className="inverse-note">启用大模型会发送任务数据；测试连接会产生少量 API 用量。</p>
    <p role="status">{pending ? '处理中' : message}</p>
    <label>外观<select aria-label="外观" value={state.preferences.theme} disabled={pending} onChange={async e => { setPending(true); try { update(await api<Workspace>('/preferences', 'PATCH', { theme: e.target.value })); } catch (error) { setMessage((error as Error).message); } finally { setPending(false); } }}><option value="light">浅色</option><option value="graphite">深色</option></select></label>
  </div></div>;
}
