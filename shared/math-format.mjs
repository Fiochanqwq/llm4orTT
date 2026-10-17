// Convert common LLM math delimiters without rewriting ordinary code samples.
function delimiters(text) {
  let result = '', i = 0;
  while (i < text.length) {
    if (text[i] === '`') {
      let end = i; while (text[end] === '`') end++;
      const marker = text.slice(i, end), close = text.indexOf(marker, end);
      if (close >= 0) { result += text.slice(i, close + marker.length); i = close + marker.length; continue; }
    }
    if (text[i] === '\\' && text[i - 1] !== '\\' && ['[', '('].includes(text[i + 1])) {
      const block = text[i + 1] === '[', end = text.indexOf(block ? '\\]' : '\\)', i + 2);
      if (end >= 0) { const body = text.slice(i + 2, end).trim(); result += block ? '\n\n$$\n' + body + '\n$$\n\n' : '$' + body + '$'; i = end + 2; continue; }
    }
    result += text[i++];
  }
  return result;
}
export function normalizeMathMarkdown(text) {
  const lines = text.split('\n'); let out = '', prose = '', fence = null, code = [];
  for (const line of lines) {
    if (!fence) {
      const match = line.match(/^ {0,3}(`{3,}|~{3,})\s*([^\s]*)[^\n]*$/);
      if (!match) { prose += line + '\n'; continue; }
      out += delimiters(prose); prose = '';
      fence = { marker: match[1], math: /^(latex|tex|math)$/i.test(match[2]) }; code = [line];
    } else {
      code.push(line);
      if (new RegExp('^ {0,3}' + fence.marker[0] + '{' + fence.marker.length + ',}\\s*$').test(line)) {
        let body = code.slice(1, -1).join('\n').trim();
        if (body.startsWith('$$') && body.endsWith('$$')) body = body.slice(2, -2).trim();
        if (body.startsWith('\\[') && body.endsWith('\\]')) body = body.slice(2, -2).trim();
        out += fence.math ? '\n$$\n' + body + '\n$$\n\n' : code.join('\n') + '\n'; fence = null; code = [];
      }
    }
  }
  return out + delimiters(prose) + (code.length ? code.join('\n') : '');
}
export function symbolLatex(name) {
  const escape = text => text.replace(/[\\{}_$%&#^~]/g, char => '\\' + char);
  const [base, ...indices] = name.split('_');
  const part = text => /^[A-Za-z]$|^\d+$/.test(text) ? text : '\\mathrm{' + escape(text) + '}';
  return part(base) + (indices.length ? '_{' + indices.map(part).join(',') + '}' : '');
}
export function modelLatex(model) {
  const symbol = symbolLatex;
  const numeric = n => String(n).replace(/e([+-]?\d+)$/i, '\\times 10^{$1}');
  const expression = terms => Object.entries(terms).filter(([, coefficient]) => coefficient !== 0).map(([name, coefficient], i) => (coefficient < 0 ? (i ? ' - ' : '-') : i ? ' + ' : '') + (Math.abs(coefficient) === 1 ? '' : numeric(Math.abs(coefficient)) + '\\,') + symbol(name)).join('') || '0';
  const rows = ['\\' + (model.sense === 'maximize' ? 'max' : 'min') + '\\quad & ' + expression(model.objective)];
  for (const c of model.constraints) rows.push('& ' + expression(c.terms) + ' ' + { '<=': '\\le', '>=': '\\ge', '=': '=' }[c.sense] + ' ' + numeric(c.rhs));
  for (const v of model.variables) {
    const x = symbol(v.name);
    if (v.type === 'binary') rows.push('& ' + x + '\\in\\{0,1\\}');
    else { if (v.lower !== null || v.upper !== null) rows.push('& ' + (v.lower !== null ? numeric(v.lower) + '\\le ' : '') + x + (v.upper !== null ? '\\le ' + numeric(v.upper) : '')); rows.push('& ' + x + '\\in\\mathbb{' + (v.type === 'integer' ? 'Z' : 'R') + '}'); }
  }
  return '\\begin{aligned}\n' + rows.join('\\\\\n') + '\n\\end{aligned}';
}
