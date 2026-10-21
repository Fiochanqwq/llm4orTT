/** End-to-end entry: study, Chinese reports, browser QA, checksummed evidence bundle. */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
const value = key => {
  const i = args.indexOf(key);
  return i < 0 ? null : args[i + 1];
};
const out = path.resolve(root, value('--out') || '实验/出版级复核_2026-10-21');
const runtime = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime');
const python = value('--report-python') || path.join(runtime, 'dependencies/python/python.exe');
const marker = path.join(runtime, 'plugins/openai-primary-runtime/plugins/pdf/skills/pdf/container_tools/mark_artifact_operation_started.mjs');
async function run(command, parameters) {
  const code = await new Promise((resolve, reject) => {
    const child = spawn(command, parameters, { cwd: root, windowsHide: true, stdio: 'inherit' });
    child.once('error', reject);
    child.once('close', resolve);
  });
  if (code !== 0) throw Error('Delivery stage failed: ' + parameters.join(' '));
}
if (!args.includes('--render-only')) {
  const studyArgs = ['scripts/publication-study.mjs', '--out', out];
  if (args.includes('--resume')) studyArgs.push('--resume');
  await run(process.execPath, studyArgs);
}
if (!fs.existsSync(python)) throw Error('Provide --report-python with reportlab/Pillow/pypdf installed.');
await run(python, ['-X', 'utf8', 'research/publication_prepare_delivery.py', '--out', out]);
await run(process.execPath, [marker, '--operation-kind', 'create', '--expected-output-count', '1', '--output-format', 'pdf']);
await run(python, ['-X', 'utf8', 'research/publication_report.py', '--out', out]);
await run(python, ['-X', 'utf8', 'research/publication_pdf_qa.py', '--out', out,
  '--pdftoppm', path.join(runtime, 'dependencies/native/poppler/Library/bin/pdftoppm.exe')]);
await run(process.execPath, ['scripts/publication-report-qa.mjs', out]);
await run(python, ['-X', 'utf8', 'research/seal_publication.py', '--out', out]);
console.log(JSON.stringify({ status: 'complete', report: path.join(out, '研究报告.pdf'), output: out }));
