import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { startServer } from '../server/http.mjs';

const directory = path.resolve('qa', 'conversation-export-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
const service = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
  generator: async function* () { throw Error('No model calls allowed'); }, planner: async () => { throw Error('No model calls allowed'); }
});
const other = service.store.create(); other.title = '不应导出的对话';
const selected = service.store.create(); selected.title = '连续对话：预算/调整？';
selected.messages.push(
  { id: 'user-fixture', role: 'user', content: '预算改为290，保留旧约束。', status: 'complete', createdAt: new Date().toISOString() },
  { id: 'answer-fixture', role: 'assistant', content: '保留的中止回答', status: 'stopped', createdAt: new Date().toISOString(), model: 'fixture-only', usage: { input: null, output: null } }
);
service.store.touch(selected);
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1360, height: 900 }, acceptDownloads: true });
const errors = []; page.on('pageerror', error => errors.push(error.message));
async function download(button, name) {
  const pending = page.waitForEvent('download'); await button.click(); const result = await pending;
  assert.match(result.suggestedFilename(), /^llm4orOvO-.*\.json$/);
  assert.ok(!/[<>:"/\\|?*]/.test(result.suggestedFilename()));
  const file = path.join(directory, name + '.json'); await result.saveAs(file);
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.deepEqual(data.conversations, [selected]);
  assert.deepEqual(data.solverRuns, []);
  assert.equal(data.conversations[0].messages[1].usage.input, null);
}
try {
  await page.goto(service.origin + '/#token=' + service.token);
  await page.getByRole('button', { name: '管理 ' + selected.title, exact: true }).click();
  await download(page.getByRole('button', { name: '导出为 JSON', exact: true }), 'sidebar-download');
  await page.getByRole('button', { name: selected.title, exact: true }).click();
  await download(page.getByRole('button', { name: '导出当前对话为 JSON', exact: true }), 'toolbar-download');
  await page.screenshot({ path: path.join(directory, 'desktop.png') });
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByLabel('语言', { exact: true }).selectOption('en');
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 430, height: 900 });
  await download(page.getByRole('button', { name: 'Export current conversation as JSON', exact: true }), 'english-narrow-download');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(directory, 'english-narrow.png') });
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify({ status: 'passed', kind: 'software_fixture_only', checks: ['sidebar JSON download', 'current conversation JSON download', 'English narrow view download', 'exact message preservation', 'other conversation excluded', 'safe filename', 'no model calls'], errors }, null, 2));
  console.log(JSON.stringify({ status: 'passed', directory }));
} finally { await browser.close(); await service.close(); }
