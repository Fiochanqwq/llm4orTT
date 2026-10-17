import { remarkMathVariables } from './remarkMathVariables';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';
import { Copy, Check, Calculator } from 'lucide-react';
import { useState, useRef, useEffect, type ComponentPropsWithoutRef } from 'react';
import { translator } from './i18n';
import type { Language } from './types';
import { normalizeMathMarkdown } from '../shared/math-format.mjs';
function CodeBlock({ children, language, onModel, ...props }: ComponentPropsWithoutRef<'pre'> & { language: Language; onModel?: (text: string) => void }) {
  const [copied, setCopied] = useState(false);
  const pre = useRef<HTMLPreElement>(null), [model, setModel] = useState('');
  useEffect(() => { const text = pre.current?.textContent || ''; try { setModel(JSON.parse(text).format === 'llm4orovo.lp.v1' ? text : ''); } catch { setModel(''); } }, [children]);
  return <div className="code-block"><button className="code-copy" aria-label={translator(language)('复制代码')} onClick={async e => { const code = e.currentTarget.parentElement?.querySelector('code')?.textContent || ''; try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1600); } catch { setCopied(false); } }}>{copied ? <Check size={14}/> : <Copy size={14}/>}</button><pre ref={pre} {...props}>{children}</pre>{model && onModel && <button className="code-solve" onClick={() => onModel(model)}><Calculator size={14}/>{language === 'en' ? 'Open in solver' : '在求解器中打开'}</button>}</div>;
}
export function Markdown({ text, language, onModel }: { text: string; language: Language; onModel?: (text: string) => void }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath, remarkMathVariables]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, trust: false, maxExpand: 500, maxSize: 20 }], rehypeHighlight]} components={{ pre: props => <CodeBlock {...props} language={language} onModel={onModel}/>, a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>, img: ({ alt }) => <span className="image-placeholder">{alt || translator(language)('图片')}</span> }}>{normalizeMathMarkdown(text)}</ReactMarkdown></div>;
}
