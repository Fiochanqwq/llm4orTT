import katex from 'katex';
import { useMemo } from 'react';
import { symbolLatex } from '../shared/math-format.mjs';

export function MathSymbol({ name }: { name: string }) {
  const html = useMemo(() => katex.renderToString(symbolLatex(name), { throwOnError: false, trust: false, output: 'htmlAndMathml' }), [name]);
  return <span className="math-symbol" title={name} dangerouslySetInnerHTML={{ __html: html }}/>;
}
