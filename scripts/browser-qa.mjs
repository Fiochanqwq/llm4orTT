import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
const stamp = new Date().toISOString().replace(/[:.]/g, '-'), directory = path.resolve('qa', 'browser-' + stamp);
fs.mkdirSync(directory, { recursive: true });
const server = await startServer({ directory: path.join(directory, 'fixture-data'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async v => Buffer.from(v).toString('base64'), unprotect: async v => Buffer.from(v, 'base64').toString() },
  generator: async function* (_config, messages, signal) {
    if (messages.at(-1).content.includes('取消')) { yield { text: '取消测试的部分输出' }; await new Promise((_r, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })); return; }
    const text = '这是一条**软件界面测试响应**，不属于研究数据。\n\n$$\\max 3x + 2y$$\n\n```python\nprint("hello")\n```\n\n<script>alert("unsafe")</script>';
    for (let i = 0; i < text.length; i += 20) { if (signal.aborted) throw new DOMException('Aborted', 'AbortError'); yield { text: text.slice(i, i + 20) }; await new Promise(r => setTimeout(r, 20)); }
    yield { usage: { input: 18, output: 29 } };
  },
  modelLister: async () => ({ models: ['qa-model'], source: 'api', verified: true }), connectionTester: async () => ({ ok: true, model: 'qa-model' })
});
server.store.data.preferences.chatMode = 'chat'; server.store.save();
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
const page = await context.newPage(), errors = [], checks = [];
page.on('pageerror', e => errors.push(e.message));
page.on('dialog', async dialog => { errors.push('Unexpected dialog: ' + dialog.message()); await dialog.dismiss(); });
const screenshot = name => page.screenshot({ path: path.join(directory, name + '.png'), fullPage: true });
try {
  await page.goto(server.origin + '/#token=' + server.token);
  await expect(page.getByRole('heading', { name: '新对话', exact: true })).toBeVisible();
  await screenshot('01-light-home'); checks.push('initial clean state');
  await page.getByRole('button', { name: '设置', exact: true }).click();
  for (const theme of ['石墨灰', '纯黑', '深蓝白', '浅白']) { await page.getByRole('button', { name: theme, exact: true }).click(); await expect(page.getByRole('button', { name: theme, exact: true })).toHaveAttribute('aria-pressed', 'true'); if (theme === '深蓝白') await screenshot('02-navy-settings'); }
  checks.push('four themes');
  await page.getByRole('button', { name: 'API', exact: true }).click();
  for (const name of ['OpenAI', 'Anthropic', 'Gemini', 'GLM', 'DeepSeek', 'Qwen']) { await page.locator('.provider-tabs').getByRole('button', { name, exact: false }).click(); await expect(page.locator('.provider-form h4')).toHaveText(name); }
  await page.getByLabel('地区', { exact: true }).selectOption('sg');
  await page.getByPlaceholder('输入 API Key').fill('qa-fake-provider-key');
  await page.getByRole('button', { name: '保存', exact: true }).click(); await expect(page.getByPlaceholder('••••••••••••••••')).toBeVisible();
  await expect(page.getByPlaceholder('••••••••••••••••')).toHaveValue('');
  await page.getByRole('button', { name: '测试连接', exact: true }).click(); await expect(page.getByRole('status')).toHaveText('连接成功');
  await screenshot('03-api-settings'); checks.push('six provider tabs, region, key masking, simulated test');
  await page.locator('.provider-tabs').getByRole('button', { name: 'OpenAI' }).click();
  await page.getByPlaceholder('输入 API Key').fill('qa-fake-openai-key'); await page.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByRole('button', { name: '关闭设置' }).click();
  await page.getByRole('textbox', { name: '消息', exact: true }).fill('请展示数学公式和代码，这是软件验收输入。'); await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.locator('.markdown')).toContainText('软件界面测试响应'); await expect(page.getByRole('button', { name: '重新生成' })).toBeVisible();
  await expect(page.locator('.katex')).toBeVisible(); await expect(page.locator('.markdown pre code')).toContainText('print'); await expect(page.locator('.markdown script')).toHaveCount(0); checks.push('streaming, math, code, HTML not executed');
  await screenshot('04-conversation');
  await page.getByRole('button', { name: '重新生成' }).click(); await expect(page.locator('.message-assistant')).toHaveCount(2); await expect(page.getByRole('button', { name: '重新生成' })).toBeVisible(); checks.push('retry preserves both outputs');
  await page.getByRole('textbox', { name: '消息', exact: true }).fill('取消测试'); await page.getByRole('button', { name: '发送消息' }).click(); await expect(page.locator('.message-assistant').last()).toContainText('取消测试的部分输出'); await page.getByRole('button', { name: '停止生成' }).click(); await expect(page.locator('.message-assistant').last()).toContainText('生成已停止'); checks.push('cancel retains partial output');
  await page.reload(); await expect(page.locator('.message-assistant')).toHaveCount(3); checks.push('persistent history');
  await page.setViewportSize({ width: 430, height: 850 }); await expect(page.getByRole('button', { name: '展开侧栏' })).toBeVisible(); await screenshot('05-narrow');
  const noOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth); expect(noOverflow).toBe(true); checks.push('narrow window no horizontal overflow');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.locator('.conversation-row').hover(); await page.getByRole('button', { name: /^管理 / }).click(); await page.getByRole('button', { name: '重命名', exact: true }).click(); await page.getByRole('textbox', { name: '对话名称' }).fill('验收记录'); await page.getByRole('textbox', { name: '对话名称' }).press('Enter'); await expect(page.locator('.conversation-title')).toHaveText('验收记录');
  await page.getByRole('textbox', { name: '搜索对话' }).fill('不存在的标题'); await expect(page.locator('.empty-history')).toContainText('没有匹配'); await page.getByRole('button', { name: '清除搜索' }).click(); checks.push('rename and search');
  await page.getByRole('button', { name: '设置', exact: true }).click(); await page.getByRole('button', { name: '数据', exact: true }).click(); const downloading = page.waitForEvent('download'); await page.getByRole('button', { name: '导出', exact: true }).click(); const download = await downloading; await download.saveAs(path.join(directory, 'export.json')); const exportText = fs.readFileSync(path.join(directory, 'export.json'), 'utf8'); expect(exportText).not.toContain('qa-fake'); expect(JSON.parse(exportText).conversations.length).toBe(1); await page.getByRole('button', { name: '关闭设置' }).click(); checks.push('export excludes secrets');
  await page.locator('.conversation-row').hover(); await page.getByRole('button', { name: /^管理 / }).click(); await page.getByRole('button', { name: '删除', exact: true }).click(); await page.getByRole('dialog').getByRole('button', { name: '删除', exact: true }).click(); await expect(page.locator('.conversation-row')).toHaveCount(0); checks.push('delete conversation');
  const exported = server.store.publicState(); expect(JSON.stringify(exported)).not.toContain('qa-fake-openai-key'); expect(errors).toEqual([]);
  const report = { date: new Date().toISOString(), kind: 'software_qa_mock_responses_not_research_data', checks, errors, status: 'passed', directory };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
} catch (error) { await screenshot('failure'); fs.writeFileSync(path.join(directory, 'failure.txt'), error.stack || String(error)); console.error(directory, error); process.exitCode = 1; }
finally { await browser.close(); await server.close(); }
