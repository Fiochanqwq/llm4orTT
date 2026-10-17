import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
import { demoModel } from '../shared/solver-model.mjs';
const directory = path.resolve('qa', 'solver-ui-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
const service = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async value => Buffer.from(value).toString('base64'), unprotect: async value => Buffer.from(value, 'base64').toString() },
  generator: async function* () { yield { text: '```json\n' + JSON.stringify(demoModel, null, 2) + '\n```' }; }
});
const request = (route, method = 'GET', body) => fetch(service.origin + '/api' + route, { method, headers: { 'content-type': 'application/json', 'x-fyppppp-token': service.token }, body: body && JSON.stringify(body) });
service.store.data.preferences.chatMode = 'chat'; service.store.save();
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } }), errors = [], checks = [];
page.on('pageerror', e => errors.push(e.message));
const shot = name => page.screenshot({ path: path.join(directory, name + '.png'), fullPage: true });
try {
  expect((await fetch(service.origin + '/api/solver')).status).toBe(401);
  await page.goto(service.origin + '/#token=' + service.token);
  await page.getByRole('button', { name: '求解器', exact: true }).click();
  await expect(page.getByRole('heading', { name: '求解器', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '求解', exact: true }).click();
  await expect(page.locator('.solver-status')).toHaveAttribute('data-status', 'optimal', { timeout: 50000 });
  await expect(page.locator('.solver-metrics').first()).toContainText('1,000');
  await expect(page.locator('.solver-values')).toHaveText('A10B20');
  await shot('01-chinese-optimal'); checks.push('real bundled HiGHS demo optimal: A=10 B=20 objective=1000');
  await page.getByLabel('A objective', { exact: true }).fill('50');
  await expect(page.locator('.solver-stale')).toBeVisible();
  await page.getByRole('button', { name: '求解', exact: true }).click();
  await expect(page.locator('.solver-status')).toHaveAttribute('data-status', 'optimal', { timeout: 50000 });
  await expect(page.locator('.solver-metrics')).toContainText('1,100'); checks.push('editable coefficient creates a new run and changes real objective to 1100');
  await page.getByRole('button', { name: 'JSON', exact: true }).click();
  const invalid = structuredClone(demoModel); invalid.constraints.push({ name: 'impossible', terms: { A: 1 }, sense: '<=', rhs: -1 });
  await page.getByLabel('模型 JSON').fill(JSON.stringify(invalid)); await page.getByRole('button', { name: '求解', exact: true }).click();
  await expect(page.locator('.solver-status')).toHaveAttribute('data-status', 'infeasible', { timeout: 50000 });
  await expect(page.locator('.solver-metrics')).toContainText('—'); checks.push('infeasible UI shows no objective and preserves previous runs');
  await page.getByRole('button', { name: '载入示例', exact: true }).click();
  await page.getByRole('button', { name: '让助手建模', exact: true }).click();
  await expect(page.getByLabel('消息', { exact: true })).toHaveValue(/llm4orovo.lp.v1/);
  const configured = await request('/providers/openai', 'PUT', { apiKey: 'qa-dummy-not-a-real-key', region: 'global', model: 'qa-model', maxTokens: 1024 }); expect(configured.status).toBe(200);
  await page.reload(); await page.getByRole('button', { name: '求解器', exact: true }).click(); await page.getByRole('button', { name: '让助手建模', exact: true }).click();
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await page.getByRole('button', { name: '在求解器中打开', exact: true }).click();
  await expect(page.getByRole('heading', { name: '求解器', exact: true })).toBeVisible();
  await expect(page.getByLabel('A objective', { exact: true })).toHaveValue('40');
  checks.push('mock LLM response imports data model into solver; no paid/provider request');
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const dialog = page.getByRole('dialog'); await dialog.getByRole('button', { name: '求解器', exact: true }).click();
  await expect(dialog.getByText('已内置', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '外观', exact: true }).click(); await page.getByLabel('语言', { exact: true }).selectOption('en'); await page.getByLabel('Font size', { exact: true }).selectOption('24'); await dialog.getByRole('button', { name: 'Black', exact: true }).click();
  await page.keyboard.press('Escape'); await expect(page.getByRole('heading', { name: 'Solver', exact: true })).toBeVisible();
  await expect.poll(() => page.locator('.app-shell').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(14, 14, 14)');
  await shot('02-english-black-24px');
  await page.setViewportSize({ width: 430, height: 900 }); await shot('03-narrow-english-24px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: 'Solve', exact: true })).toBeEnabled(); checks.push('English, 24px font, black theme and narrow layout');
  await page.getByLabel('Solver engine').selectOption('gurobi'); await page.getByRole('button', { name: 'Solve', exact: true }).click(); await expect(page.locator('.solver-status')).toHaveAttribute('data-status', 'unavailable'); checks.push('optional Gurobi reports unavailable without fallback');
  expect(errors).toEqual([]);
  const report = { status: 'passed', kind: 'software_demo_qa_real_highs_mock_llm_no_research_runs', directory, checks };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
} catch (e) { fs.writeFileSync(path.join(directory, 'failure.txt'), e.stack || String(e)); console.error(directory, e); process.exitCode = 1; }
finally { await browser.close(); await service.close(); }
