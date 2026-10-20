import { _electron, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { extractFile, listPackage } from '@electron/asar';

const version = JSON.parse(fs.readFileSync('package.json', 'utf8')).version;
const executablePath = path.resolve(process.argv[2] || 'release/' + version + '/win-unpacked/llm4orTT.exe');
const directory = path.resolve('qa', 'inverse-desktop-' + Date.now());
const output = path.resolve('outputs/inverse');
fs.mkdirSync(directory, { recursive: true }); fs.mkdirSync(output, { recursive: true });
const archive = path.join(path.dirname(executablePath), 'resources/app.asar');
const entries = listPackage(archive);
if (entries.some(f => /^[/\\](node_modules|qa|\.local|test|experiments|baselines)([/\\]|$)/.test(f))) throw Error('Development data was packaged');
if (entries.some(f => /(?:experiments-cli|optimization|compact-protocol|slime)/i.test(f))) throw Error('Legacy modules were packaged');
const solverFiles = fs.readdirSync(path.join(path.dirname(executablePath), 'resources/solver')).sort();
if (JSON.stringify(solverFiles) !== JSON.stringify(['inverse.py', 'inverse_benchmark.py', 'inverse_local.py'])) throw Error('Unexpected solver modules: ' + solverFiles.join(','));
if (JSON.parse(extractFile(archive, 'package.json')).version !== version) throw Error('Wrong packaged version');
fs.mkdirSync(path.join(directory, 'workspace'), { recursive: true });
fs.writeFileSync(path.join(directory, 'workspace/workspace.json'), JSON.stringify({ version: 1, preferences: {}, providers: {}, conversations: [{ id: 'legacy-chat-fixture', title: '以前的普通对话', messages: [{ id: 'old-user', role: 'user', content: '普通聊天内容恢复检查' }] }] }));
const app = await _electron.launch({ executablePath, env: { ...process.env, FYPPPPP_QA: '1', FYPPPPP_DATA_DIR: path.join(directory, 'workspace'), FYPPPPP_PORT: '43139' }, timeout: 45000 });
try {
  const page = await app.firstWindow(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await expect(page.getByRole('heading', { name: '今天想聊些什么？' })).toBeVisible();
  await page.getByRole('button', { name: '以前的普通对话', exact: true }).click();
  await expect(page.getByText('普通聊天内容恢复检查', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: '逆优化工作台' }).click();
  await expect(page.getByRole('heading', { name: '从经验中，还原规则' })).toBeVisible();
  for (const name of ['实验工作台', '求解器']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '运行三步重构' }).click();
  await expect(page.getByRole('heading', { name: '恢复结果', exact: true })).toBeVisible({ timeout: 90000 });
  await expect(page.getByText('逆问题已通过求解器最优性检查', { exact: false })).toBeVisible();
  await expect(page.locator('.inverse-hypothesis b').first()).toHaveText('夜班负担');
  const exportPath = path.join(directory, 'export.json');
  // Electron uses its native download/save flow rather than Playwright's browser download event.
  await app.evaluate(({ BrowserWindow }, filename) => {
    BrowserWindow.getAllWindows()[0].webContents.session.once('will-download', (_event, item) => item.setSavePath(filename));
  }, exportPath);
  await page.getByRole('button', { name: '导出证据' }).click();
  await expect.poll(() => { try { return JSON.parse(fs.readFileSync(exportPath, 'utf8')).status; } catch { return ''; } }).toBe('optimal');
  fs.copyFileSync(exportPath, path.join(output, 'desktop-solver-evidence.json'));
  const evidence = JSON.parse(fs.readFileSync(exportPath, 'utf8'));
  if (evidence.spending?.modelCalls !== 0 || !evidence.localAnalysis?.identification?.ranges.length) throw Error('Packaged local analysis did not complete without model calls');
  if (evidence.status !== 'optimal' || !evidence.versions.highspy || !evidence.inputSha256) throw Error('Incomplete solver evidence');
  await page.locator('.inverse-workspace').evaluate(element => { element.scrollTop = 0; });
  if (errors.length) throw Error(errors.join('\n'));
  const report = { status: 'passed', executablePath, workspace: directory, version, meanResidual: evidence.meanResidual, solver: evidence.versions,
    checks: ['packaged Electron starts', 'ordinary chat restored', 'legacy chat text migration', 'inverse workbench retained', 'bundled Python and HiGHS solve', 'Chinese text intact', 'evidence export', 'no development data packaged', 'no renderer errors'] };
  fs.writeFileSync(path.join(output, 'desktop-qa.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally { await app.close(); }
