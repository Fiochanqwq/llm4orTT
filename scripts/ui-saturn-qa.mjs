import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { startServer } from '../server/http.mjs';
import { demoModel } from '../shared/solver-model.mjs';

const directory = path.resolve('qa', 'saturn-model-export');
fs.mkdirSync(directory, { recursive: true });
const service = await startServer({ directory: path.join(directory, 'workspace-' + Date.now()), staticDir: path.resolve('dist'), port: 0 });
const model = JSON.parse(JSON.stringify(demoModel).replaceAll('"A"', '"x_1"').replaceAll('"B"', '"x_2"'));
const selected = service.store.create(); selected.title = '下标显示检查';
selected.messages.push({ id: 'math-fixture', role: 'assistant', status: 'complete', createdAt: new Date().toISOString(), content: '变量 x_1 与 `x_12`，索引 x_{i,j}。已有公式 $x_2$。\n\n```\nx_3\n```\n\n[文件 x_4](https://example.com/x_4)\n\n文件 x_5.py 保持原样。', automation: { stage: 'complete', showModel: true, result: { id: 'fixture', invoked: false, status: 'optimal', model, engine: 'highs', values: {}, versions: {} } } });
service.store.touch(selected);
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1360, height: 950 }, acceptDownloads: true });
const errors = []; page.on('pageerror', e => errors.push(e.message));
try {
  await page.goto(service.origin + '/#token=' + service.token);
  await expect(page.getByRole('img', { name: 'Saturn Logo' }).first()).toBeVisible();
  await page.getByRole('button', { name: selected.title, exact: true }).click();
  await expect(page.locator('.markdown .katex')).toHaveCount(4);
  await expect(page.locator('.markdown pre')).toHaveText('x_3\n');
  await expect(page.locator('.markdown a')).toHaveText('文件 x_4');
  await expect(page.locator('.markdown')).toContainText('文件 x_5.py 保持原样。');
  await expect(page.locator('.automation-model .model-export')).toBeVisible();
  await page.screenshot({ path: path.join(directory, 'chat.png') });
  await page.evaluate(model => localStorage.setItem('llm4orovo-solver-draft', JSON.stringify(model)), model);
  await page.getByRole('button', { name: '求解器', exact: true }).click();
  await expect(page.locator('.solver-form .math-symbol').first()).toBeVisible();
  for (const format of ['lp', 'json', 'py', 'tex']) {
    await page.getByLabel('模型文件格式').selectOption(format);
    const promise = page.waitForEvent('download'); await page.getByRole('button', { name: '导出模型', exact: true }).click();
    const download = await promise; assert.ok(download.suggestedFilename().endsWith('.' + format));
    await download.saveAs(path.join(directory, 'model.' + format));
  }
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(directory, 'model.json'), 'utf8')), model);
  const output = execFileSync(path.resolve('runtime/python/python.exe'), ['-c', 'import highspy,sys; h=highspy.Highs(); assert h.readModel(sys.argv[1]) == highspy.HighsStatus.kOk; h.run(); assert h.getModelStatus() == highspy.HighsModelStatus.kOptimal; assert abs(h.getObjectiveValue()-1000)<1e-7; print("LP roundtrip passed")', 'model.lp'], { encoding: 'utf8', cwd: directory });
  assert.match(output, /LP roundtrip passed/);
  await page.getByRole('button', { name: '公式', exact: true }).click();
  await expect(page.locator('.solver-model-math msub').first()).toBeAttached();
  await page.screenshot({ path: path.join(directory, 'solver.png') });
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await expect(page.locator('.theme-mini-main .saturn')).toHaveCount(4);
  await page.getByLabel('语言', { exact: true }).selectOption('en');
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 430, height: 900 });
  await expect(page.getByRole('button', { name: 'Export model', exact: true })).toBeVisible();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(directory, 'narrow.png') });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', directory, checks: ['prose and model subscripts', 'code and links preserved', 'all four download formats', 'LP solved by HiGHS: objective 1000', 'theme preview logos', 'English narrow layout'], errors }));
} finally { await browser.close(); await service.close(); }
