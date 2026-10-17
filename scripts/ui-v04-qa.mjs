import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
const directory = path.resolve('qa', 'ui-v04-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
const response = String.raw`这是软件测试回复。即使这里声称“已运行求解器”，来源标签也应保持模型回复。

行内公式：\(x_1 + x_2 = 3\)。

\[\max\; 40A+30B \quad \text{s.t.}\; 2A+B\le40\]

$$\begin{pmatrix}1&2\\3&4\end{pmatrix}$$

` + '```latex\n\\frac{1}{2}+\\sum_{i=1}^{n}x_i\n```\n\n' + '```python\ntext = "\\[literal code\\]"\n```\n\n' + String.raw`\[\href{javascript:alert(1)}{unsafe}\]`;
const server = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async x => Buffer.from(x).toString('base64'), unprotect: async x => Buffer.from(x, 'base64').toString() },
  generator: async function* (_config, messages) { const text = messages.at(-1).content.includes('[Local solver record') ? String.raw`这是根据真实本地记录生成的解释：\(A=10,\ B=20\)，目标为 \(1000\)。` : response; for (let i = 0; i < text.length; i += 35) { yield { text: text.slice(i, i + 35) }; await new Promise(r => setTimeout(r, 10)); } }
});
server.store.data.preferences.chatMode = 'chat'; server.store.save();
await server.store.configure('openai', { apiKey: 'qa-fake-not-real', region: 'global', model: 'qa-model', maxTokens: 2048 });
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = [], checks = [];
page.on('pageerror', e => errors.push(e.message)); page.on('dialog', async d => { errors.push(d.message()); await d.dismiss(); });
const shot = name => page.screenshot({ path: path.join(directory, name + '.png'), animations: 'disabled' });
try {
  await page.goto(server.origin + '/#token=' + server.token);
  await page.getByLabel('消息', { exact: true }).fill('软件验收：展示公式，不是研究数据'); await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止生成', exact: true })).toHaveCount(0, { timeout: 15000 });
  await expect(page.locator('.message-provenance')).toHaveAttribute('data-source', 'llm');
  await expect(page.locator('.markdown .katex-html')).toHaveCount(5);
  await expect(page.locator('.markdown .code-block pre')).toContainText('\\[literal code\\]');
  expect(await page.locator('.markdown a[href^="javascript:"]').count()).toBe(0);
  await page.locator('.message-scroll').evaluate(e => { e.scrollTop = 0; }); await shot('01-model-response-latex');
  checks.push('streamed inline, display, matrix, fenced LaTeX render; Python code remains literal; unsafe math links do not execute');
  checks.push('fake solver claim in mock LLM text does not create application provenance');
  await page.getByRole('button', { name: '求解器', exact: true }).click(); await page.getByRole('button', { name: '公式', exact: true }).click();
  await expect(page.locator('.solver-model-math .katex-html')).toBeVisible();
  await page.getByRole('button', { name: '求解', exact: true }).click(); await expect(page.locator('.solver-status')).toHaveAttribute('data-status', 'optimal', { timeout: 50000 });
  await expect(page.locator('.solver-proof')).toHaveAttribute('data-execution', 'invoked');
  await page.getByText('执行凭证', { exact: true }).click(); await expect(page.locator('.solver-proof')).toContainText('highspy'); await shot('02-actual-solver-proof');
  checks.push('actual HiGHS result has engine versions, run ID, SHA256 and rendered model');
  await page.getByRole('button', { name: '让助手解释', exact: true }).click(); await expect(page.locator('.solver-context-chip')).toBeVisible();
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  const linked = page.locator('.message-provenance[data-source="llm-solver-interpretation"]'); await expect(linked).toBeVisible();
  await expect(page.getByRole('button', { name: '停止生成', exact: true })).toHaveCount(0, { timeout: 15000 });
  await shot('03-interpretation-with-linked-record');
  await linked.getByRole('button').click(); await expect(page.locator('.solver-values')).toHaveText('A10B20');
  await expect(page.getByLabel('模型名称', { exact: true })).toHaveValue('Production demo');
  checks.push('interpretation attaches server-resolved record; click navigates to exact original model and result');
  await page.getByRole('button', { name: '设置', exact: true }).click(); await page.getByLabel('语言', { exact: true }).selectOption('en'); await page.getByLabel('Font size', { exact: true }).selectOption('24'); await page.getByRole('button', { name: 'Black', exact: true }).click(); await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 430, height: 900 }); await page.getByRole('button', { name: 'Math', exact: true }).click();
  await expect.poll(() => page.locator('.app-shell').evaluate(e => getComputedStyle(e).backgroundColor)).toBe('rgb(14, 14, 14)'); await shot('04-narrow-math');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(errors).toEqual([]); checks.push('English 24px dark narrow math layout');
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify({ status: 'passed', kind: 'software_qa_real_highs_mock_llm', directory, checks }, null, 2)); console.log(JSON.stringify({ directory, checks }));
} catch (e) { fs.writeFileSync(path.join(directory, 'failure.txt'), e.stack || String(e)); await shot('failure').catch(() => {}); console.error(directory, e); process.exitCode = 1; }
finally { await browser.close(); await server.close(); }
