/** One entry point: preflight, frozen computation, independent audit, analysis. */
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { solverPython } from '../server/python-runtime.mjs';
import { auditLocalApi } from './publication-api.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
if (args.includes('--language-only') && !args.includes('--language'))
  throw Error('--language-only requires --language');
const temporaryRoot = path.join(root, 'work', 'tmp');
if (!args.includes('--language-only')) {
  fs.mkdirSync(temporaryRoot, { recursive: true });
  for (const key of ['TEMP', 'TMP', 'TMPDIR']) process.env[key] = temporaryRoot;
}
const option = name => {
  const i = args.indexOf(name);
  if (i < 0) return null;
  if (!args[i + 1] || args[i + 1].startsWith('--')) throw Error('Missing value for ' + name);
  return args[i + 1];
};
const out = path.resolve(root, option('--out') || '实验/出版级复核_2026-10-21');
const relative = path.relative(path.join(root, '实验'), out);
if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw Error('Use a new batch inside the experiment archive');
fs.mkdirSync(path.join(out, 'logs'), { recursive: true });
let serial = 0;
async function run(label, command, parameters) {
  const filename = `${new Date().toISOString().replaceAll(':', '-')}-${++serial}-${label}.log`;
  const log = fs.createWriteStream(path.join(out, 'logs', filename), { flags: 'wx' });
  const started = Date.now();
  console.log(JSON.stringify({ phase: label, status: 'started' }));
  const code = await new Promise((resolve, reject) => {
    const child = spawn(command, parameters, { cwd: root, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' } });
    const timeout = setTimeout(() => child.kill(), label === 'language-stage' ? 10800000 : label === 'scientific-study' ? 3600000 : 180000);
    child.stdout.on('data', chunk => { log.write(chunk); process.stdout.write(chunk); });
    child.stderr.on('data', chunk => { log.write(chunk); process.stderr.write(chunk); });
    child.once('error', error => { clearTimeout(timeout); reject(error); });
    child.once('close', code => { clearTimeout(timeout); resolve(code); });
  }).finally(() => new Promise(resolve => log.end(resolve)));
  fs.appendFileSync(path.join(out, 'lifecycle.jsonl'), JSON.stringify({
    phase: label, exitCode: code, wallSeconds: (Date.now() - started) / 1000,
    finishedUTC: new Date().toISOString(), log: 'logs/' + filename,
  }) + '\n');
  if (code !== 0) throw Error(label + ' failed; retained log: ' + filename);
}
const python = solverPython(root);
if (args.includes('--language')) {
  if (args.includes('--resume') || args.includes('--audit-only'))
    throw Error('Language calls require a new batch; automatic replay/retry is forbidden');
  const languageArgs = ['scripts/research-language-study.mjs', '--out', out];
  if (args.includes('--language-density')) languageArgs.push('--density');
  if (args.includes('--language-prepared')) languageArgs.push('--prepared');
  await run('language-stage', process.execPath, languageArgs);
  if (args.includes('--language-only')) {
    await run('language-summary', python, ['-B', '-X', 'utf8', 'research/publication_pipeline.py', '--out', out, '--language-only']);
    console.log(JSON.stringify({ status: 'complete', output: out, summary: path.join(out, 'language/summary.json') }));
    process.exit(0);
  }
}
if (!args.includes('--resume') && !args.includes('--audit-only')) {
  if (fs.existsSync(path.join(out, 'freeze.json'))) throw Error('Study exists; use --resume');
  await run('certification-tests', process.execPath, ['scripts/certification-test.mjs']);
  await run('application-tests', process.execPath, [
    '--test', '--test-timeout=60000', 'test/inverse.test.mjs', 'test/inverse-economy.test.mjs',
    'test/workspace.test.mjs', 'test/providers.test.mjs', 'test/launcher.test.mjs',
    'test/loopback.test.mjs', 'test/chat.test.mjs',
  ]);
  await run('typescript', process.execPath, ['node_modules/typescript/bin/tsc', '--noEmit']);
  await run('frontend-build', process.execPath, ['node_modules/vite/bin/vite.js', 'build']);
  console.log(JSON.stringify({ phase: 'authenticated-api', ...(await auditLocalApi(out)) }));
}
const parameters = ['-X', 'utf8', 'research/publication_pipeline.py', '--out', out];
if (option('--protocol')) parameters.push('--protocol', option('--protocol'));
if (args.includes('--resume')) parameters.push('--resume');
if (args.includes('--audit-only')) parameters.push('--audit-only');
await run('scientific-study', python, parameters);
console.log(JSON.stringify({ status: 'complete', output: out, reportData: path.join(out, 'analysis.json') }));
