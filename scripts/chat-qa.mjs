import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';

const directory = path.resolve('qa', 'chat-ui-' + Date.now()); fs.mkdirSync(directory, { recursive: true });
let calls = 0;
const seen = [];
const service = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async x => x, unprotect: async x => x },
  generator: async function* (config, messages, signal) {
    calls++; seen.push({ purpose: config.purpose, roles: messages.map(m => m.role) });
    yield { text: '这是**普通聊天**的回复。\n\n' };
    if (messages.at(-1).content === '慢一点') {
      await new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }));
    }
    yield { text: '公式：$x^2+1$\n\n```python\nprint("hello")\n```' };
  } });
let browser;
try {
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(service.origin + '/#token=' + service.token);
  await expect(page.getByRole('heading', { name: '今天想聊些什么？' })).toBeVisible();
  await page.getByLabel('输入消息').fill('你好'); await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '设置' })).toBeVisible();
  await page.getByLabel('API Key').fill('fixture-key'); await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('已保存'); await page.getByRole('button', { name: '关闭设置' }).click();
  await page.getByLabel('输入消息').press('Enter');
  await expect(page.locator('.chat-message.assistant strong')).toHaveText('普通聊天');
  await expect(page.locator('.chat-message .katex')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '重新生成' })).toBeEnabled();
  await page.getByLabel('输入消息').fill('再聊聊'); await page.getByLabel('输入消息').press('Enter');
  await expect(page.locator('.chat-message')).toHaveCount(4);
  await expect(page.getByRole('button', { name: '重新生成' })).toBeEnabled();
  if (seen[1].roles.join(',') !== 'user,assistant,user' || seen.some(x => x.purpose !== 'chat')) throw Error('Lost ordinary conversation context');
  await page.getByRole('button', { name: '重命名对话' }).click(); await page.getByLabel('对话标题').fill('日常聊天'); await page.getByRole('button', { name: '保存标题' }).click();
  await expect(page.locator('.chat-title')).toHaveText('日常聊天');
  await page.getByRole('tab', { name: '逆优化工作台' }).click(); await expect(page.getByRole('heading', { name: '从经验中，还原规则' })).toBeVisible();
  await page.getByRole('tab', { name: '普通对话' }).click(); await expect(page.locator('.chat-message')).toHaveCount(4);
  const download = page.waitForEvent('download'); await page.getByRole('button', { name: '导出对话' }).click(); await (await download).saveAs(path.join(directory, 'chat.json'));
  if (JSON.parse(fs.readFileSync(path.join(directory, 'chat.json'), 'utf8')).messages.length !== 4) throw Error('Chat export incomplete');
  await page.reload(); await expect(page.locator('.chat-message')).toHaveCount(4); await expect(page.locator('.chat-title')).toHaveText('日常聊天');
  await page.screenshot({ path: path.join(directory, 'chat.png'), fullPage: true });
  await page.getByRole('button', { name: '重新生成' }).click(); await expect.poll(() => calls).toBe(3); await expect(page.getByRole('button', { name: '重新生成' })).toBeEnabled(); await expect(page.locator('.chat-message')).toHaveCount(4);
  await page.getByLabel('输入消息').fill('慢一点'); await page.getByLabel('输入消息').press('Enter'); await expect(page.getByRole('button', { name: '停止生成' })).toBeVisible();
  await page.getByRole('button', { name: '停止生成' }).click(); await expect(page.getByText('已停止生成', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '新建对话', exact: true }).click(); await page.getByLabel('输入消息').fill('草稿保留'); await page.reload(); await expect(page.getByLabel('输入消息')).toHaveValue('草稿保留');
  await page.getByRole('navigation', { name: '聊天记录' }).getByRole('button', { name: '日常聊天', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '收起历史列表' }).click();
  await page.screenshot({ path: path.join(directory, 'mobile.png'), fullPage: true });
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('Mobile overflow');
  await page.getByRole('button', { name: '删除对话' }).click(); await page.getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByRole('heading', { name: '今天想聊些什么？' })).toBeVisible();
  if (errors.length) throw Error(errors.join('\n'));
  console.log(JSON.stringify({ status: 'passed', directory, calls, checks: ['default ordinary chat', 'key setup', 'streaming', 'multi-turn context', 'Markdown and formula', 'rename', 'history reload', 'inverse tab preserved', 'export', 'retry', 'stop', 'new chat', 'draft persistence', 'delete', 'mobile layout'] }));
} finally { await browser?.close(); await service.close(); }
