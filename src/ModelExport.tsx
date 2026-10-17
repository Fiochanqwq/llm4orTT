import { useId, useState } from 'react';
import { Download } from 'lucide-react';
import { exportModel, type ModelFormat } from '../shared/model-export.mjs';
import type { LinearModel } from '../shared/solver-model.mjs';
import type { Language } from './types';

export function ModelExport({ model, language, engine = 'highs', seconds = 30 }: { model: LinearModel | null; language: Language; engine?: string; seconds?: number }) {
  const [format, setFormat] = useState<ModelFormat>('lp'), [error, setError] = useState('');
  const id = useId(), en = language === 'en';
  function save() {
    if (!model) return;
    try {
      const file = exportModel(model, format, engine, seconds);
      const url = URL.createObjectURL(new Blob([file.text], { type: file.type }));
      const link = document.createElement('a'); link.href = url; link.download = file.name;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000); setError('');
    } catch (e) { setError((e as Error).message); }
  }
  return <div className="model-export"><label htmlFor={id}>{en ? 'Model format' : '模型文件格式'}</label><select id={id} value={format} onChange={e => setFormat(e.target.value as ModelFormat)}>
    <option value="lp">LP (.lp)</option><option value="json">JSON (.json)</option><option value="py">Pyomo (.py)</option><option value="tex">LaTeX (.tex)</option>
  </select><button className="secondary-button" disabled={!model || (format === 'py' && (!Number.isInteger(seconds) || seconds < 1 || seconds > 120))} onClick={save}><Download size={14}/>{en ? 'Export model' : '导出模型'}</button>{error && <p role="alert">{error}</p>}</div>;
}
