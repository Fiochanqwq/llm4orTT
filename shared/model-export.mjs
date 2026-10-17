import { validateModel, pyomoSource } from './solver-model.mjs';
import { modelLatex } from './math-format.mjs';

// LP identifiers are prefixed to avoid reserved solver words such as "bounds".
export function modelLP(input) {
  const model = validateModel(input);
  const numeric = n => {
    const [mantissa, exponent] = String(n).split('e');
    if (!exponent) return mantissa;
    const negative = mantissa.startsWith('-'), digits = mantissa.replace('-', '').replace('.', '');
    const point = mantissa.replace('-', '').split('.')[0].length + Number(exponent);
    return (negative ? '-' : '') + (point <= 0 ? '0.' + '0'.repeat(-point) + digits : point >= digits.length ? digits + '0'.repeat(point - digits.length) : digits.slice(0, point) + '.' + digits.slice(point));
  };
  const expression = terms => Object.entries(terms).filter(([, value]) => value !== 0).map(([name, value], i) => `${value < 0 ? '- ' : i ? '+ ' : ''}${numeric(Math.abs(value))} v_${name}`).join(' ');
  const lines = ['\\ llm4orOvO LP model; variable v_NAME corresponds to original NAME', model.sense === 'maximize' ? 'Maximize' : 'Minimize', ' obj: ' + expression(model.objective), 'Subject To'];
  for (const c of model.constraints) lines.push(` c_${c.name}: ${expression(c.terms)} ${c.sense} ${numeric(c.rhs)}`);
  if (!model.constraints.length) lines.push(` c_empty: 0 v_${model.variables[0].name} = 0`);
  lines.push('Bounds');
  for (const v of model.variables) {
    const name = 'v_' + v.name;
    if (v.lower === null && v.upper === null) lines.push(` ${name} free`);
    else lines.push(` ${v.lower === null ? '-inf' : numeric(v.lower)} <= ${name}${v.upper === null ? '' : ' <= ' + numeric(v.upper)}`);
  }
  for (const [type, section] of [['integer', 'Generals'], ['binary', 'Binaries']]) {
    const variables = model.variables.filter(v => v.type === type);
    if (variables.length) lines.push(section, ...variables.map(v => ' v_' + v.name));
  }
  return lines.concat('End', '').join('\n');
}

export function exportModel(input, format, engine = 'highs', seconds = 30) {
  const model = validateModel(input);
  const filename = (model.name.trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, '-').replace(/[. ]+$/g, '').slice(0, 80) || 'model');
  const contents = {
    json: () => JSON.stringify(model, null, 2) + '\n',
    lp: () => modelLP(model),
    py: () => pyomoSource(model, engine, seconds),
    tex: () => '\\documentclass{article}\n\\usepackage{amsmath,amssymb}\n\\begin{document}\n\\[\n' + modelLatex(model) + '\n\\]\n\\end{document}\n'
  };
  if (!Object.hasOwn(contents, format)) throw new Error('Unsupported model format');
  return { text: contents[format](), name: filename + '.' + format, type: format === 'json' ? 'application/json' : 'text/plain;charset=utf-8' };
}
