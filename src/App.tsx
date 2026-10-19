import { useEffect, useState } from 'react';
import { Settings as SettingsIcon } from 'lucide-react';
import { Inverse } from './Inverse';
import { Settings } from './Settings';
import { Chat } from './Chat';
import { api } from './api';
import type { Workspace } from './types';
import packageInfo from '../package.json';

export default function App() {
  const [state, setState] = useState<Workspace | null>(null), [settings, setSettings] = useState(false), [error, setError] = useState('');
  const [view, setView] = useState(sessionStorage.getItem('workspace-view') === 'inverse' ? 'inverse' : 'chat');
  const selectView = (next: string) => { setView(next); sessionStorage.setItem('workspace-view', next); };
  const refresh = () => api<Workspace>('/state').then(setState).catch(e => setError(e.message));
  useEffect(() => { refresh(); document.title = 'llm4orTT'; }, []);
  useEffect(() => { document.documentElement.dataset.theme = state?.preferences.theme || 'light'; }, [state?.preferences.theme]);
  if (!state) return <div className="loading-screen"><p role="status">{error || '正在打开工作台'}</p>{error && <button onClick={refresh}>重新连接</button>}</div>;
  const current = state.providers[state.preferences.provider];
  return <main className="workspace">
    <header className="app-bar"><div className="app-brand"><img src="/saturn-icon.png" alt=""/><b>llm4orTT</b><small>v{packageInfo.version.replace(/\.0$/, '')}</small></div><nav className="app-tabs" aria-label="工作区"><button role="tab" aria-selected={view === 'chat'} onClick={() => selectView('chat')}>普通对话</button><button role="tab" aria-selected={view === 'inverse'} onClick={() => selectView('inverse')}>逆优化工作台</button></nav><div className="app-tools"><span>{current.hasKey ? current.model : '本地模式'}</span><button onClick={() => setSettings(true)}><SettingsIcon size={17}/>设置</button></div></header>
    <div className="app-pane" hidden={view !== 'chat'}><Chat state={state} update={setState} settings={() => setSettings(true)}/></div>
    <div className="app-pane" hidden={view !== 'inverse'}><Inverse provider={state.preferences.provider}/></div>
    {settings && <Settings state={state} update={setState} close={() => setSettings(false)}/>}
  </main>;
}
