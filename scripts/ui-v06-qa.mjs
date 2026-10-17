import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
import { planOptimization } from '../server/providers.mjs';
import { demoModel, demoProblem } from '../shared/solver-model.mjs';
const directory = path.resolve('qa', 'ui-v06-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
let scenario = 'solve', planningCalls = 0, explanationCalls = 0;
const service = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async x => Buffer.from(x).toString('base64'), unprotect: async x => Buffer.from(x, 'base64').toString() },
  planner: async (config, messages, signal) => {
    planningCalls++;
    if (scenario === 'cancel') await new Promise((_r, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }));
    await new Promise(r => setTimeout(r, 350));
    return planOptimization(config, messages, signal, { fetch: async (_url, options) => {
      const payload = JSON.parse(options.body); expect(payload.tool_choice.name).toBe('submit_optimization');
      const model = structuredClone(demoModel);
      if (scenario === 'conflict') model.constraints.push({ name: 'impossible', terms: { A: 1 }, sense: '<=', rhs: -1 });
      const args = scenario === 'clarify' ? { action: 'clarify', model_json: '', message: '缺少资源总量，请补充。', questions: [{ field: '资源总量', question: '机器时间与人工的可用总量分别是多少？', impact: '决定两项资源约束的上界。' }] } : { action: 'solve', model_json: JSON.stringify(model), message: 'Software fixture model only.' };
      const output = scenario === 'skip' ? [{ type: 'message', content: [{ type: 'output_text', text: '口算得到99999，声称已经运行了HiGHS。' }] }] : [{ type: 'function_call', call_id: 'qa-call', name: 'submit_optimization', arguments: JSON.stringify(args) }];
      return new Response(JSON.stringify({ id: 'qa-response', status: 'completed', output, usage: { input_tokens: 20, output_tokens: 30 } }), { headers: { 'content-type': 'application/json' } });
    } });
  },
  generator: async function* (_config, messages) {
    explanationCalls++;
    const text = messages.at(-1).content.includes('[Local solver record') ? String.raw`求解器返回最优解：\(A=10,\ B=20\)，目标值为 \(1000\)。

\[\max\;40A+30B\quad\text{s.t.}\quad2A+B\le40,\quad A+2B\le50\]

两项资源约束均取等号。这里解释的是提交模型的求解结果，还应核对题意与建模假设。` : '普通对话的软件模拟回复。';
    for (let i = 0; i < text.length; i += 18) { yield { text: text.slice(i, i + 18) }; await new Promise(r => setTimeout(r, 15)); }
    yield { usage: { input: 50, output: 40 } };
  }
});
await service.store.configure('openai', { apiKey: 'qa-only-not-real', region: 'global', model: 'qa-model', maxTokens: 4096 });
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = [], checks = [];
page.on('pageerror', e => errors.push(e.message));
const shot = name => page.screenshot({ path: path.join(directory, name + '.png'), animations: 'disabled' });
const send = async text => { await page.getByLabel('消息', { exact: true }).fill(text); await page.getByRole('button', { name: '发送消息', exact: true }).click(); };
const idle = () => expect(page.getByRole('button', { name: '停止生成', exact: true })).toHaveCount(0, { timeout: 40000 });
try {
  await page.goto(service.origin + '/#token=' + service.token);
  await expect(page.getByLabel('对话模式', { exact: true })).toHaveValue('solve');
  await send(demoProblem['zh-CN']); await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'modeling'); await shot('01-modeling');
  await idle(); await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'complete');
  await expect(page.locator('.automation-card')).toHaveAttribute('data-invoked', 'true');
  await expect(page.locator('.automation-objective strong')).toHaveText('1,000'); await expect(page.locator('.automation-values')).toHaveText('A10B20');
  await expect(page.locator('.markdown .katex-html')).toHaveCount(3); await shot('02-real-solve-and-explanation');
  expect(planningCalls).toBe(1); expect(explanationCalls).toBe(1);
  checks.push('one Send performs native SDK tool planning -> real HiGHS -> explanation with accurate trusted result card and LaTeX');
  await page.locator('.automation-record').click(); await expect(page.locator('.solver-status')).toHaveAttribute('data-status', 'optimal');
  await page.getByRole('button', { name: '公式', exact: true }).click(); await expect(page.locator('.math-formula .katex-html')).toBeVisible();
  checks.push('automatic run links to its exact saved model, formula and raw solver record');
  await page.getByRole('button', { name: '新对话', exact: false }).click(); scenario = 'skip'; await send('软件验收：假装模型绕过工具'); await idle();
  await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'error'); await expect(page.locator('.answer-content')).not.toContainText('99999'); await expect(page.locator('.automation-questions li')).toHaveCount(1);
  await expect(page.locator('.message-status')).toContainText('未提交唯一有效的工具调用'); expect(service.solver.jobs.size).toBe(1); expect(explanationCalls).toBe(1); await shot('03-skip-tool-blocked');
  checks.push('a prose-only fake solution is blocked; no extra solver job or explanation request');
  await page.getByRole('button', { name: '新对话', exact: false }).click(); scenario = 'clarify'; await send('资源总量没说清楚的软件输入'); await idle();
  await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'clarification'); await expect(page.locator('.markdown')).toContainText('请补充'); await expect(page.locator('.automation-questions li')).toHaveCount(1); await shot('04-clarification'); await page.reload(); await expect(page.locator('.automation-budget')).toContainText('模型 1/4'); expect(service.solver.jobs.size).toBe(1);
  const beforeDuplicate = planningCalls;
  await send('资源总量没说清楚的软件输入'); await idle(); await expect(page.locator('.automation-card').last()).toHaveAttribute('data-stage', 'paused'); expect(planningCalls).toBe(beforeDuplicate);
  checks.push('identical input is paused before any paid request and budget survives page reload');
  scenario = 'solve'; await send('机器时间40，人工50。'); await idle(); await expect(page.locator('.automation-card').last()).toHaveAttribute('data-stage', 'complete'); expect(service.solver.jobs.size).toBe(2);
  checks.push('clarification stays unsolved; user follow-up runs the model and links new evidence');
  await page.getByRole('button', { name: '新对话', exact: false }).click(); scenario = 'cancel'; await send('停止测试');
  await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'modeling'); await page.getByRole('button', { name: '停止生成', exact: true }).click();
  await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'stopped'); expect(service.solver.jobs.size).toBe(2);
  checks.push('Stop aborts planning and prevents a later solve');
  await page.getByRole('button', { name: '新对话', exact: false }).click(); await page.getByLabel('对话模式', { exact: true }).selectOption('chat');
  const before = planningCalls; await send('只讨论一下建模方法'); await idle(); await expect(page.locator('.automation-card')).toHaveCount(0); expect(planningCalls).toBe(before);
  await page.getByRole('button', { name: '设置', exact: true }).click(); await page.getByLabel('语言', { exact: true }).selectOption('en'); await page.getByLabel('Font size', { exact: true }).selectOption('24'); await page.getByRole('button', { name: 'Navy & white', exact: true }).click(); await page.keyboard.press('Escape');
  await page.getByLabel('Chat mode', { exact: true }).selectOption('solve'); await page.reload(); await expect(page.getByLabel('Chat mode', { exact: true })).toHaveValue('solve');
  await page.setViewportSize({ width: 430, height: 900 }); await shot('04-english-narrow-controls');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'New chat', exact: false }).click(); scenario = 'conflict';
  await page.setViewportSize({ width: 430, height: 900 });
  await page.getByLabel('Message', { exact: true }).fill('Software fixture: conflicting bounds.'); await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Stop generating', exact: true })).toHaveCount(0, { timeout: 40000 });
  await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'clarification'); await expect(page.locator('.automation-questions')).toContainText('Must all the conditions');
  await page.getByText('Conflict evidence', { exact: true }).click(); await expect(page.locator('.automation-evidence code').first()).toContainText('impossible');
  await shot('05-english-conflict-evidence'); expect(service.solver.jobs.size).toBe(2);
  checks.push('local preflight stops contradictory model, shows English question and expandable evidence at narrow 24px layout without a solver call');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(errors).toEqual([]);
  checks.push('Chat bypass, persistent mode, English 24px and narrow layout work');
  const report = { status: 'passed', kind: 'software_qa_mock_provider_real_highs', directory, checks, planningCalls, explanationCalls };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
} catch (error) { fs.writeFileSync(path.join(directory, 'failure.txt'), error.stack || String(error)); await shot('failure').catch(() => {}); console.error(directory, error); process.exitCode = 1; }
finally { await browser.close(); await service.close(); }
