import { _electron, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { Store } from '../server/store.mjs';

const version = JSON.parse(fs.readFileSync('package.json', 'utf8')).version;
const directory = path.resolve('qa', 'export-desktop-' + new Date().toISOString().replace(/[:.]/g, '-'));
const dataDir = path.join(directory, 'workspace');
const store = new Store(dataDir, {}), conversation = store.create();
conversation.title = '桌面导出验收';
conversation.messages.push({ id: 'fixture', role: 'user', content: '独立测试数据，不是实际实验。', status: 'complete', createdAt: new Date().toISOString() });
store.touch(conversation);
const app = await _electron.launch({ executablePath: path.resolve(`release/${version}/win-unpacked/llm4orOvO.exe`), env: { ...process.env, FYPPPPP_DATA_DIR: dataDir, FYPPPPP_PORT: '0', FYPPPPP_QA: '1' }, timeout: 30000 });
try {
  const page = await app.firstWindow();
  await page.getByRole('button', { name: conversation.title, exact: true }).click();
  await expect(page.getByRole('button', { name: '导出当前对话为 JSON', exact: true })).toBeVisible();
  const output = path.join(directory, 'desktop-download.json');
  await app.evaluate(({ BrowserWindow }, file) => {
    globalThis.exportDownload = new Promise(resolve => {
      BrowserWindow.getAllWindows()[0].webContents.session.once('will-download', (_event, item) => {
        item.setSavePath(file);
        item.once('done', (_event, state) => resolve(state));
      });
    });
  }, output);
  await page.getByRole('button', { name: '导出当前对话为 JSON', exact: true }).click();
  const state = await app.evaluate(async () => await Promise.race([globalThis.exportDownload, new Promise(resolve => setTimeout(() => resolve('timeout'), 15000))]));
  assert.equal(state, 'completed');
  const exported = JSON.parse(fs.readFileSync(output, 'utf8'));
  assert.deepEqual(exported.conversations, [conversation]);
  const report = { status: 'passed', kind: 'packaged_desktop_fixture_only', version, output };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally { await app.close(); }
