import { useMemo } from 'react';
import katex from 'katex';
export function MathFormula({ text }: { text: string }) {
  const html = useMemo(() => katex.renderToString(text, { displayMode: true, output: 'htmlAndMathml', throwOnError: false, trust: false, strict: 'ignore', maxExpand: 500, maxSize: 20 }), [text]);
  return <div className="math-formula" dangerouslySetInnerHTML={{ __html: html }}/>;
}
