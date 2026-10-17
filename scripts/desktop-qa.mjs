import { _electron, chromium, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const stamp = new Date().toISOString().replace(/[:.]/g, '-'), directory = path.resolve('qa', 'desktop-' + stamp);
fs.mkdirSync(directory, { recursive: true });
const executablePath = path.resolve(process.env.FYPPPPP_QA_EXECUTABLE || `release/${JSON.parse(fs.readFileSync('package.json', 'utf8')).version}/win-unpacked/llm4orOvO.exe`);
const env = { ...process.env, FYPPPPP_DATA_DIR: path.join(directory, 'workspace'), FYPPPPP_PORT: '43128', FYPPPPP_QA: '1' };
const checks = [], app = await _electron.launch({ executablePath, env, timeout: 30000 });
let browser;
try {
  const page = await app.firstWindow(); await expect(page.getByRole('heading', { name: '新对话', exact: true })).toBeVisible();
  checks.push('packaged desktop boots (hidden window; visual QA recorded separately in browser screenshots)');
  const preferences = await app.evaluate(({ BrowserWindow }) => { const p = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences(); return { node: p.nodeIntegration, isolated: p.contextIsolation, sandbox: p.sandbox }; });
  expect(preferences).toEqual({ node: false, isolated: true, sandbox: true }); checks.push('renderer isolation');
  await page.getByRole('button', { name: '求解器', exact: true }).click();
  await page.getByRole('button', { name: '求解', exact: true }).click();
  await expect(page.locator('.solver-status')).toHaveAttribute('data-status', 'optimal', { timeout: 50000 });
  await expect(page.locator('.solver-values strong')).toHaveText(['10', '20']);
  await expect(page.locator('.solver-metrics')).toContainText('1,000');
  checks.push('packaged bundled Python/Pyomo/HiGHS solves real demo');
  await expect(page.locator('.solver-proof')).toContainText('实际调用');
  await page.getByRole('button', { name: '公式', exact: true }).click();
  await expect(page.locator('.katex').first()).toBeVisible();
  checks.push('packaged actual invocation badge and compiled model formula');
  const autoResult = await app.evaluate(async ({ app }, folder) => {
    const load = process.mainModule.require.bind(process.mainModule), path = load('node:path');
    const root = app.getAppPath();
    const { startServer } = load(path.join(root, 'server/http.mjs'));
    const { demoModel } = load(path.join(root, 'shared/solver-model.mjs'));
    let plans = 0, explanations = 0, scenario = 'solve';
    const testServer = await startServer({ directory: folder, staticDir: path.join(root, 'dist'), port: 0,
      secretVault: { protect: async x => 'test:' + x, unprotect: async x => x.slice(5) },
      planner: async () => { plans++; return { calls: [{ name: 'submit_optimization', arguments: scenario === 'solve' ? { action: 'solve', model_json: JSON.stringify(demoModel), message: '', questions: [] } : { action: 'clarify', model_json: '', message: 'Capacity missing.', questions: [{ field: 'capacity', question: 'What is the capacity?', impact: 'Sets a bound.' }] } }], usage: { input: 1, output: 2 } }; },
      generator: async function* (_config, messages) { explanations++; if (!messages.at(-1).content.includes('"objective":1000')) throw Error('Missing real solver data'); yield { text: 'Packaged automation QA only', usage: { input: 3, output: 4 } }; }
    });
    try {
      await testServer.store.configure('openai', { apiKey: 'fake-qa-only', region: 'global', model: 'qa-model', maxTokens: 1024 });
      testServer.store.data.preferences.methodPreset = 'legacy'; // Packaged legacy comparison; v0.7 UI checks use the v2 fixture.
      const c = testServer.store.create();
      const response = await fetch(testServer.origin + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json', 'x-fyppppp-token': testServer.token }, body: JSON.stringify({ conversationId: c.id, provider: 'openai', message: 'Packaged software fixture only' }) });
      await response.text(); const answer = c.messages.at(-1);
      const summary = { status: answer.status, stage: answer.automation?.stage, objective: answer.automation?.result?.objective, values: answer.automation?.result?.values, invoked: answer.automation?.result?.invoked, usage: answer.usage, plans, explanations };
      const retry = await fetch(testServer.origin + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json', 'x-fyppppp-token': testServer.token }, body: JSON.stringify({ conversationId: c.id, provider: 'openai', retry: true }) }); await retry.text();
      summary.retryBlocked = plans === 1 && c.messages.at(-1).automation.decision.code === 'no_new_information' && c.messages.at(-1).automation.task.calls === 2;
      const next = testServer.store.create(); scenario = 'clarify';
      const follow = await fetch(testServer.origin + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json', 'x-fyppppp-token': testServer.token }, body: JSON.stringify({ conversationId: next.id, provider: 'openai', message: 'Need capacity' }) }); await follow.text();
      summary.clarified = next.messages.at(-1).automation.stage === 'clarification' && next.messages.at(-1).automation.questions.length === 1 && explanations === 1;
      return summary;
    } finally { await testServer.close(); }
  }, path.join(directory, 'automatic-workspace'));
  expect(autoResult).toEqual({ status: 'complete', stage: 'complete', objective: 1000, values: { A: 10, B: 20 }, invoked: true, usage: { input: 4, output: 6 }, plans: 1, explanations: 1, retryBlocked: true, clarified: true });
  checks.push('packaged auto workflow uses one model submission, real HiGHS and one interpretation with traceable values');
  checks.push('packaged agent blocks duplicate paid requests, persists counts and asks structured clarification without an explanation call');
  await page.getByRole('button', { name: '新对话', exact: false }).click();
  await page.getByRole('button', { name: '设置', exact: true }).click(); await page.locator('.theme-card').filter({ hasText: '深蓝白' }).click();
  await page.getByRole('button', { name: 'API', exact: true }).click(); await page.getByPlaceholder('输入 API Key').fill('qa-only-secret-not-a-real-api-key'); await page.getByRole('button', { name: '保存', exact: true }).click(); await expect(page.getByRole('status')).toHaveText('已保存');
  const persisted = fs.readFileSync(path.join(env.FYPPPPP_DATA_DIR, 'workspace.json'), 'utf8'); expect(persisted).not.toContain('qa-only-secret-not-a-real-api-key'); expect(JSON.parse(persisted).providers.openai.encryptedKey).toBeTruthy(); checks.push('packaged DPAPI persistence');
  await page.getByRole('button', { name: '外观', exact: true }).click();
  await page.getByLabel('字号', { exact: true }).selectOption('22');
  await expect.poll(() => page.locator('.composer textarea').evaluate(element => getComputedStyle(element).fontSize)).toBe('22px');
  await page.getByLabel('语言', { exact: true }).selectOption('en'); await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page).toHaveTitle('llm4orOvO'); checks.push('packaged rename, font and English settings');
  const runtime = JSON.parse(fs.readFileSync(path.join(env.FYPPPPP_DATA_DIR, 'runtime.json'), 'utf8'));
  browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const browserPage = await browser.newPage({ viewport: { width: 1440, height: 960 } }); await browserPage.goto(runtime.origin + '/#token=' + runtime.token);
  await expect(browserPage.locator('html')).toHaveAttribute('data-theme', 'navy'); await expect(browserPage.locator('.connection-state')).toContainText('Configured');
  await expect(browserPage.locator('html')).toHaveAttribute('lang', 'en'); await expect.poll(() => browserPage.locator('.composer textarea').evaluate(element => getComputedStyle(element).fontSize)).toBe('22px'); checks.push('browser sees desktop theme, language, font and key status');
  await browserPage.getByRole('button', { name: 'Solver', exact: true }).click();
  await expect(browserPage.locator('.solver-status')).toHaveAttribute('data-status', 'optimal');
  await expect(browserPage.locator('.solver-values strong')).toHaveText(['10', '20']);
  await browserPage.screenshot({ path: path.join(directory, 'packaged-browser-solver.png') });
  checks.push('browser reads the actual desktop solve record');
  await browserPage.getByRole('button', { name: 'New chat', exact: false }).click();
  await page.close(); await browserPage.reload(); await expect(browserPage.getByRole('heading', { name: 'New chat', exact: true })).toBeVisible(); checks.push('browser survives desktop window closing');
  await app.close(); await browser.close(); browser = null;
  // Standalone browser mode: the executable starts the service without a desktop window.
  const browserEnv = { ...env, FYPPPPP_DATA_DIR: path.join(directory, 'browser-only'), FYPPPPP_PORT: '43129' };
  const browserApp = await _electron.launch({ executablePath, args: ['--browser'], env: browserEnv, timeout: 30000 });
  try {
    for (let i = 0; i < 100 && !fs.existsSync(path.join(browserEnv.FYPPPPP_DATA_DIR, 'runtime.json')); i++) await new Promise(r => setTimeout(r, 100));
    const runtime2 = JSON.parse(fs.readFileSync(path.join(browserEnv.FYPPPPP_DATA_DIR, 'runtime.json'), 'utf8'));
    expect(await browserApp.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length)).toBe(0);
    const response = await fetch(runtime2.origin + '/api/state', { headers: { 'x-fyppppp-token': runtime2.token } }); expect(response.status).toBe(200); checks.push('independent browser mode has no desktop window');
  } finally { await browserApp.close(); }
  const report = { status: 'passed', kind: 'software_qa_no_provider_requests', date: new Date().toISOString(), checks, directory, executablePath };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
} catch (error) { console.error(directory, error); fs.writeFileSync(path.join(directory, 'failure.txt'), error.stack || String(error)); process.exitCode = 1; }
finally { if (browser) await browser.close(); await app.close().catch(() => {}); }
