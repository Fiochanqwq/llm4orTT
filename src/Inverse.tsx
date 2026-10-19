import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Download, FlaskConical, Play, Square, Upload } from 'lucide-react';
import { api } from './api';
import './inverse.css';

type Hypothesis = { id: string; label: string; source: string; weight: number; retained: boolean };
type Result = {
  id: string; status: string; method: string; meanResidual: number; elapsedMs: number; stopReason: string;
  hypotheses: Hypothesis[]; anomalies: { id: string; residual: number }[];
  residuals: { id: string; residual: number }[];
  trace: { iteration: number; gap: number; cutsAdded: number }[];
  history: { round: number; meanResidual: number; status: string; accepted?: boolean }[];
  input: Record<string, unknown>;
};
type Saved = { id: string; createdAt: string; meanResidual: number; status: string };
const format = (n: number) => Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: 5 }) : '未计算';

export function Inverse({ provider }: { provider: string }) {
  const [draft, setDraft] = useState(() => sessionStorage.getItem('inverse-draft-v1') || ''), [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [useLLM, setUseLLM] = useState(false);
  const [saved, setSaved] = useState<Saved[]>([]), [stale, setStale] = useState(false);
  const controller = useRef<AbortController | null>(null), file = useRef<HTMLInputElement>(null);
  const refresh = () => api<Saved[]>('/inverse/runs').then(setSaved).catch(e => setError(e.message));
  useEffect(() => {
    let mounted = true;
    if (!draft) api('/inverse/demo').then(value => { if (mounted) setDraft(JSON.stringify(value, null, 2)); }).catch(e => { if (mounted) setError(e.message); });
    refresh();
    return () => { mounted = false; controller.current?.abort(); };
  }, []);
  const edit = (value: string) => { setDraft(value); setStale(!!result); try { sessionStorage.setItem('inverse-draft-v1', value); } catch { /* Keep the editor usable when session storage is full. */ } };
  const run = async () => {
    setError('');
    try {
      const input = JSON.parse(draft);
      controller.current = new AbortController(); setBusy(true);
      const value = await api<Result>('/inverse/recover', 'POST', { input, provider, useLLM, rounds: 3 }, controller.current.signal);
      setResult(value); setStale(false); await refresh();
    } catch (e) { setError((e as Error).name === 'AbortError' ? '本次运行已停止。' : (e as Error).message); }
    finally { setBusy(false); controller.current = null; }
  };
  const exportResult = () => {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'contextual-inverse-' + result.id + '.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  let sampleCount = 0, hypothesisCount = 0, title = '文本与历史决策，一起还原隐性规则', description = '', logs = '', valid = false;
  try { const parsed = JSON.parse(draft); sampleCount = parsed.samples?.length || 0; hypothesisCount = parsed.hypotheses?.length || 0; title = parsed.title || title; description = parsed.description || ''; logs = (parsed.logs || []).join('\n'); valid = true; } catch { /* The editor may temporarily contain incomplete JSON. */ }
  const changeText = (key: string, value: unknown) => { try { edit(JSON.stringify({ ...JSON.parse(draft), [key]: value }, null, 2)); } catch { setError('请先修复历史数据 JSON 格式'); } };
  const formula = (id: string) => {
    const samples = result?.input.samples as { features: Record<string, { terms: Record<string, number>; kind?: string; rhs?: number; sense?: string }> }[] | undefined;
    const feature = samples?.[0]?.features[id];
    if (!feature) return id;
    const terms = Object.entries(feature.terms).filter(([, v]) => v !== 0).map(([n, v]) => `${v}·${n}`).join(' + ') || '0';
    return feature.kind === 'soft' ? `max(0, ${feature.sense === '<=' ? `(${terms}) − ${feature.rhs}` : `${feature.rhs} − (${terms})`})` : `(${terms})`;
  };
  return <section className="inverse-workspace">
    <header className="inverse-heading"><div><span className="inverse-eyebrow">CONTEXTUAL INVERSE OPTIMIZATION · 初版</span><h1>从经验中，还原规则</h1><p>融合运营日志与历史人工决策，让隐性偏好变成可检查的数学公式。</p></div><span className="inverse-tag"><FlaskConical size={15}/> 研究工作台</span></header>
    <div className="inverse-steps"><div><b>01</b><span>文本引导的结构假设<small>把抱怨、备注变成待估计的规则</small></span></div><ArrowRight size={18}/><div><b>02</b><span>自动逆优化重构<small>用历史选择反推未知权重</small></span></div><ArrowRight size={18}/><div><b>03</b><span>稀疏正则化精炼<small>剔除弱假设，反馈异常样本</small></span></div></div>
    <div className="inverse-columns"><div className="inverse-card">
      <div className="inverse-card-title"><h2>任务与历史</h2><span>{sampleCount} 组历史 · {hypothesisCount} 个候选</span></div>
      <p>{title}</p><div className="inverse-actions">
        <button disabled={busy} onClick={async () => { try { edit(JSON.stringify(await api('/inverse/demo'), null, 2)); } catch(e) { setError((e as Error).message); } }}>载入排班示例</button>
        <button disabled={busy} onClick={() => file.current?.click()}><Upload size={14}/> 导入 JSON</button>
        <input ref={file} type="file" accept=".json,application/json" hidden onChange={async e => { const f = e.target.files?.[0]; if (!f) return; try { if (f.size > 2 * 1024 * 1024) throw Error('文件不能超过 2 MB'); edit(JSON.stringify(JSON.parse(await f.text()), null, 2)); } catch(error) { setError((error as Error).message); } e.target.value = ''; }}/>
      </div>
      <label className="inverse-editor-label" htmlFor="inverse-description">不完整的任务描述</label>
      <textarea id="inverse-description" className="inverse-text" value={description} disabled={busy || !valid} onChange={e => changeText('description', e.target.value)}/>
      <label className="inverse-editor-label" htmlFor="inverse-logs">运营日志 · 一行一条</label>
      <textarea id="inverse-logs" className="inverse-text inverse-logs" value={logs} disabled={busy || !valid} onChange={e => changeText('logs', e.target.value.split('\n'))}/>
      <details className="inverse-data"><summary>查看或编辑历史决策与候选模型 · JSON</summary><label className="inverse-editor-label" htmlFor="inverse-input">任务、日志、候选特征与历史决策</label>
      <textarea id="inverse-input" className="inverse-editor" spellCheck={false} value={draft} disabled={busy} onChange={e => edit(e.target.value)}/></details>
      <label className="inverse-toggle"><input type="checkbox" checked={useLLM} disabled={busy} onChange={e => { setUseLLM(e.target.checked); setStale(!!result); }}/>使用已配置的大模型补充结构假设并自动反馈（最多 3 轮）</label>
      <p className="inverse-note">示例由真实求解器生成，日志使用固定模板。可离线运行；启用大模型后，任务文本与训练样本将发送给所选服务商。</p>
      <div className="inverse-run">{busy ? <><span role="status">正在拟合权重并验证残差</span><button onClick={() => controller.current?.abort()}><Square size={14}/>停止</button></> : <button className="primary-button" onClick={run} disabled={!draft}><Play size={15}/>运行三步重构</button>}</div>
      {error && <p className="solver-error" role="alert">{error}</p>}
    </div><div className="inverse-results">
      {result ? <>
        <div className="inverse-card"><div className="inverse-card-title"><h2>恢复结果</h2><button onClick={exportResult}><Download size={15}/>导出证据</button></div>
          {stale && <p className="solver-stale">输入已改变，以下是上一次运行结果。</p>}
          <div className="inverse-metrics"><div><span>平均次优性残差</span><strong>{format(result.meanResidual)}</strong></div><div><span>保留假设</span><strong>{result.hypotheses.filter(h => h.retained).length}<small> / {result.hypotheses.length}</small></strong></div><div><span>异常历史样本</span><strong>{result.anomalies.length}</strong></div></div>
          <p className="inverse-note">{result.status === 'optimal' ? '逆问题已通过求解器最优性检查' : '达到迭代上限，结果尚未收敛'} · {result.method === 'strong_duality' ? 'LP 强对偶重构' : '整数前向求解与反例迭代'}</p>
          <p className="inverse-note">权重不一定唯一。零残差表示能解释这些历史选择，不代表已经恢复唯一的真实规则。</p>
        </div>
        <div className="inverse-card"><h2>经验 → 白盒规则</h2><p className="inverse-note">下列公式展示第一个历史上下文中的成本项；其余上下文保存在导出证据中。</p>{result.hypotheses.map(h => <article className={'inverse-hypothesis ' + (!h.retained ? 'pruned' : '')} key={h.id}><div><b>{h.label}</b><span>{h.retained ? '保留' : '剔除'} · θ = {format(h.weight)}</span></div><p>“{h.source || '用户提供的候选假设'}”</p><code>{format(h.weight)} × {formula(h.id)}</code></article>)}</div>
        <div className="inverse-card"><h2>残差与反馈</h2><p className="inverse-note">条越长，表示这条历史选择越难被当前规则解释。</p><div className="inverse-bars">{result.residuals.map(r => <div key={r.id}><span>{r.id}</span><div><i style={{ width: `${100 * r.residual / Math.max(.000001, ...result.residuals.map(x => x.residual))}%` }}/></div><b>{format(r.residual)}</b></div>)}</div>
          <p className="inverse-note">{({ template_only: '本轮使用输入中的结构假设，未调用大模型。', residual_threshold: '残差已低于反馈阈值。', residual_plateau: '残差进入平台期，自动停止。', proposal_not_improved: '补充假设未改善拟合，保留上一轮结果。', round_limit: '已达到自动反馈轮数上限。' } as Record<string, string>)[result.stopReason]}</p>
          <details><summary>查看求解与反馈轨迹</summary><pre>{JSON.stringify({ feedback: result.history.map(({ round, meanResidual, status, accepted }) => ({ round, meanResidual, status, accepted })), solver: result.trace }, null, 2)}</pre></details>
        </div>
      </> : <div className="inverse-card inverse-empty"><FlaskConical size={42}/><h2>让历史选择解释“为什么”</h2><p>先运行内置示例。系统会估计夜班、交接与跨区支援的隐性代价，并检查“排班表颜色”是否只是无关线索。</p><p className="inverse-note">这是合成排班演示，尚不是 NLP4LP 100 模型评测结果。</p></div>}
      {!!saved.length && <div className="inverse-card"><h2>最近运行</h2>{saved.slice(0, 8).map(s => <button className="inverse-saved" key={s.id} disabled={busy} onClick={async () => { try { const value = await api<Result>('/inverse/runs/' + s.id); setResult(value); setDraft(JSON.stringify(value.input, null, 2)); setStale(false); } catch(e) { setError((e as Error).message); } }}><span>{new Date(s.createdAt).toLocaleString()}</span><span>残差 {format(s.meanResidual)}</span></button>)}</div>}
    </div></div>
  </section>;
}
