export const demoModel = {
  format: 'llm4orovo.lp.v1', name: 'Production demo', sense: 'maximize',
  variables: [{ name: 'A', type: 'integer', lower: 0, upper: null }, { name: 'B', type: 'integer', lower: 0, upper: null }],
  objective: { A: 40, B: 30 },
  constraints: [
    { name: 'machine', terms: { A: 2, B: 1 }, sense: '<=', rhs: 40 },
    { name: 'labor', terms: { A: 1, B: 2 }, sense: '<=', rhs: 50 }
  ]
};
export const demoProblem = {
  'zh-CN': '生产 A、B 两种产品，每件收益分别为 40、30。每件 A 消耗 2 单位机器时间、1 单位人工；每件 B 消耗 1 单位机器时间、2 单位人工。机器时间总量 40，人工总量 50。产量为非负整数，最大化总收益。',
  en: 'Produce products A and B with profits of 40 and 30 per unit. A uses 2 units of machine time and 1 unit of labor; B uses 1 unit of machine time and 2 units of labor. There are 40 units of machine time and 50 units of labor. Quantities must be nonnegative integers. Maximize total profit.'
};
export function validateModel(input) {
  const fail = (field, message) => { throw new Error(field + ': ' + message); };
  const object = (x, field, keys) => { if (!x || typeof x !== 'object' || Array.isArray(x)) fail(field, 'expected object'); for (const k of Object.keys(x)) if (!keys.includes(k)) fail(field + '.' + k, 'unsupported field'); };
  const number = (x, field) => { if (typeof x !== 'number' || !Number.isFinite(x) || Math.abs(x) > 1e9) fail(field, 'expected finite number between -1e9 and 1e9'); };
  const name = (x, field) => { if (typeof x !== 'string' || !/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(x)) fail(field, 'use 1–40 ASCII letters, numbers or underscores, starting with a letter'); };
  object(input, 'model', ['format', 'name', 'sense', 'variables', 'objective', 'constraints']);
  if (input.format !== 'llm4orovo.lp.v1') fail('format', 'expected llm4orovo.lp.v1');
  if (typeof input.name !== 'string' || input.name.length > 100) fail('name', 'expected text up to 100 characters');
  if (!['maximize', 'minimize'].includes(input.sense)) fail('sense', 'expected maximize or minimize');
  if (!Array.isArray(input.variables) || input.variables.length < 1 || input.variables.length > 200) fail('variables', 'expected 1–200 variables');
  const names = new Set();
  for (const v of input.variables) {
    object(v, 'variable', ['name', 'type', 'lower', 'upper']); name(v.name, 'variable.name');
    if (names.has(v.name)) fail(v.name, 'duplicate variable'); names.add(v.name);
    if (!['continuous', 'integer', 'binary'].includes(v.type)) fail(v.name, 'unsupported variable type');
    for (const key of ['lower', 'upper']) if (v[key] !== null) number(v[key], v.name + '.' + key);
    if (v.lower !== null && v.upper !== null && v.lower > v.upper) fail(v.name, 'lower > upper');
    if (v.type === 'binary' && (v.lower !== 0 || v.upper !== 1)) fail(v.name, 'binary bounds must be 0 and 1');
  }
  let nonzeros = 0;
  function terms(values, field) {
    if (!values || typeof values !== 'object' || Array.isArray(values) || !Object.keys(values).length) fail(field, 'expected nonempty coefficient object');
    for (const [key, value] of Object.entries(values)) { if (!names.has(key)) fail(field + '.' + key, 'unknown variable'); number(value, field + '.' + key); nonzeros++; }
    if (!Object.values(values).some(v => v !== 0)) fail(field, 'at least one coefficient must be nonzero');
  }
  terms(input.objective, 'objective');
  if (!Array.isArray(input.constraints) || input.constraints.length > 500) fail('constraints', 'expected 0–500 constraints');
  const constraintNames = new Set();
  for (const c of input.constraints) {
    object(c, 'constraint', ['name', 'terms', 'sense', 'rhs']); name(c.name, 'constraint.name');
    if (constraintNames.has(c.name)) fail(c.name, 'duplicate constraint'); constraintNames.add(c.name);
    terms(c.terms, c.name + '.terms'); number(c.rhs, c.name + '.rhs');
    if (!['<=', '>=', '='].includes(c.sense)) fail(c.name, 'expected <=, >= or =');
  }
  if (nonzeros > 20000) fail('model', 'too many coefficients');
  return JSON.parse(JSON.stringify(input));
}
export function pyomoSource(input, engine = 'highs', seconds = 30) {
  const m = validateModel(input), q = JSON.stringify;
  const expression = terms => Object.entries(terms).filter(([, v]) => v !== 0).map(([k, v]) => `${v} * model.x[${q(k)}]`).join(' + ');
  const lines = ['import pyomo.environ as pyo', '', 'model = pyo.ConcreteModel()', `model.x = pyo.Var(${q(m.variables.map(v => v.name))}, domain=pyo.Reals)`];
  for (const v of m.variables) lines.push(`model.x[${q(v.name)}].domain = pyo.${{ continuous: 'Reals', integer: 'Integers', binary: 'Binary' }[v.type]}`, `model.x[${q(v.name)}].setlb(${v.lower === null ? 'None' : v.lower})`, `model.x[${q(v.name)}].setub(${v.upper === null ? 'None' : v.upper})`);
  lines.push(`model.objective = pyo.Objective(expr=${expression(m.objective)}, sense=pyo.${m.sense})`, 'model.constraints = pyo.ConstraintList()');
  for (const c of m.constraints) lines.push(`# ${c.name}`, `model.constraints.add(${expression(c.terms)} ${c.sense === '=' ? '==' : c.sense} ${c.rhs})`);
  lines.push('', `solver = pyo.SolverFactory(${q(engine === 'gurobi' ? 'gurobi_direct' : 'appsi_highs')}${engine === 'gurobi' ? ', manage_env=True' : ''})`, `solver.options[${q(engine === 'gurobi' ? 'TimeLimit' : 'time_limit')}] = ${seconds}`, 'results = solver.solve(model, tee=True, load_solutions=False)', 'print(results.solver.termination_condition)', 'if len(results.solution):', '    model.solutions.load_from(results)', '    print("objective", pyo.value(model.objective))', '    for name in model.x:', '        print(name, model.x[name].value)');
  if (engine === 'gurobi') lines.push('solver.close()');
  return lines.join('\n') + '\n';
}
export function modelingPrompt(problem, language = 'zh-CN') {
  const instruction = language === 'en' ? 'Model the problem below as LP/MILP. Return one JSON code block in the exact example format. Use ASCII identifiers, continuous/integer/binary types, explicit lower/upper bounds (null means unbounded), and constraint senses <=, >= or =. Ask if essential data is missing. Do not claim to have run a solver.' : '将下方问题建成 LP/MILP。输出一个 JSON 代码块，严格采用示例格式。名称使用英文字母/数字/下划线，变量类型为 continuous/integer/binary，显式给出 lower/upper（null 为无界），约束方向为 <=、>= 或 =。关键信息缺失时先提问。不要声称已运行求解器。';
  return instruction + '\n\n' + (language === 'en' ? 'Example problem:\n' : '示例问题：\n') + demoProblem[language] + '\n```json\n' + JSON.stringify(demoModel, null, 2) + '\n```\n\n' + (language === 'en' ? 'Problem to model:\n' : '待建模问题：\n') + problem;
}
