import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
import { demoModel, demoProblem } from '../shared/solver-model.mjs';
const directory = path.resolve('qa', 'ui-v062-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
let scenario = 'normal', plans = 0, explanations = 0;
const budgets = [], checks = [], errors = [];
const service = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
 secretVault: { protect: async x => 'test:' + x, unprotect: async x => x.slice(5) },
 planner: async config => {
  plans++; budgets.push({ stage: 'model', maxTokens: config.maxTokens });
  const model = structuredClone(demoModel);
  if (scenario === 'infeasible') model.constraints = [{ name: 'sum', terms: { A: 1, B: 1 }, sense: '=', rhs: 1 }, { name: 'equal', terms: { A: 1, B: -1 }, sense: '=', rhs: 0 }];
  if (scenario === 'long') { model.variables = Array.from({ length: 12 }, (_, i) => ({ name: 'x' + (i + 1), type: 'integer', lower: 0, upper: 1 })); model.objective = Object.fromEntries(model.variables.map(v => [v.name, 1])); model.constraints = []; }
  const args = scenario === 'clarify' ? { action: 'clarify', model_json: '', message: '缺少资源总量。', questions: [{ field: '资源', question: '可用资源总量是多少？', impact: '决定资源约束的上界。' }] } : { action: 'solve', model_json: JSON.stringify(model), message: '使用题目给定资源和整数变量建立线性模型。', questions: [] };
  return { calls: [{ name: 'submit_optimization', arguments: args }], usage: { input: 20, output: 30 } };
 },
 generator: async function* (config, messages, signal) {
  explanations++; budgets.push({ stage: 'explanation', maxTokens: config.maxTokens, inputCharacters: messages.reduce((n, m) => n + m.content.length, 0) });
  if (scenario === 'error') throw Error('Software fixture interpretation error');
  if (scenario === 'cancel') await new Promise((_r, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }));
  yield { text: config.language === 'en' ? 'Both resources are fully used. The interpretation of the original requirements still needs review.' : '两项资源均已用满。方案按提交模型计算，题意对应关系仍需核对。', usage: { input: 50, output: 25 } };
 }
});
await service.store.configure('openai', { apiKey: 'software-test-only', region: 'global', model: 'qa-model', maxTokens: 4096 });
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.on('pageerror', e => errors.push(e.message));
const shot = name => page.screenshot({ path: path.join(directory, name + '.png') });
const send = async (text = demoProblem['zh-CN']) => { await page.getByLabel('消息', { exact: true }).fill(text); await page.getByRole('button', { name: '发送消息', exact: true }).click(); };
const idle = () => expect(page.getByRole('button', { name: '停止生成', exact: true })).toHaveCount(0, { timeout: 45000 });
const fresh = async s => { scenario = s; await page.getByRole('button', { name: '新对话', exact: false }).click(); };
try {
 await page.goto(service.origin + '/#token=' + service.token);
 await expect(page.getByRole('img', { name: 'Saturn Logo' }).first()).toBeVisible();
 await shot('01-saturn'); await send(); await idle();
 await expect(page.locator('.automation-objective strong')).toHaveText('1,000');
 await expect(page.locator('.automation-values')).toHaveText('A10B20');
 await expect(page.locator('.automation-model')).not.toHaveAttribute('open');
 await expect(page.locator('.automation-details')).not.toHaveAttribute('open');
 await expect(page.locator('.automation-reasoning')).not.toHaveAttribute('open');
 await page.locator('.message-scroll').evaluate(el => el.scrollTop = 0); await shot('02-compact-answer');
 await page.getByText('推理摘要', { exact: true }).click(); await expect(page.locator('.automation-reasoning')).toContainText('实际调用');
 await page.getByText('完整模型', { exact: true }).click(); await expect(page.locator('.automation-model .katex-html')).toBeVisible();
 await page.getByText('执行记录', { exact: true }).click(); await expect(page.locator('.automation-details')).toContainText('0.6.2-compact-1');
 expect(plans).toBe(1); expect(explanations).toBe(1); await shot('03-expanded-evidence');
 checks.push('Saturn, compact deterministic result, expandable CoT summary, executed LaTeX and trace without extra calls');
 await fresh('long'); await send('软件夹具：十二个变量的完整方案'); await idle();
 await expect(page.locator('.automation-values>span')).toHaveCount(12); await expect(page.locator('.automation-values')).toContainText('x12'); await shot('04-complete-long-solution');
 checks.push('12-variable solution retained without truncation');
 await fresh('infeasible'); const before = explanations; await send('软件夹具：整数不可行'); await idle();
 await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'complete'); await expect(page.locator('.automation-result-heading')).toContainText('无可行解');
 await expect(page.locator('.automation-questions')).toHaveCount(0); await expect(page.locator('.automation-objective')).toHaveCount(0); expect(explanations).toBe(before); await shot('05-infeasible-delivered');
 checks.push('real integer infeasibility delivered without forced question or paid interpretation');
 await fresh('error'); await send(); await idle(); await expect(page.locator('.automation-objective strong')).toHaveText('1,000'); await expect(page.locator('.automation-interpretation')).toContainText('解读失败'); await expect(page.locator('.automation-questions')).toHaveCount(0); await shot('06-result-survives-interpretation-error');
 await fresh('cancel'); await send(); await expect(page.locator('.automation-card')).toHaveAttribute('data-stage', 'interpreting', { timeout: 45000 }); await page.getByRole('button', { name: '停止生成', exact: true }).click(); await idle(); await expect(page.locator('.automation-objective strong')).toHaveText('1,000'); await expect(page.locator('.automation-interpretation')).toContainText('解读停止');
 checks.push('interpretation failure and cancellation preserve genuine objective and complete solution');
 await fresh('clarify'); await send('缺少资源'); await idle(); await expect(page.locator('.automation-questions li')).toHaveCount(1); await expect(page.locator('.automation-decision')).toHaveText('缺少资源总量。'); await expect(page.locator('.answer-content')).not.toContainText('缺少资源总量。');
 checks.push('necessary clarification once, without duplicated summary');
 await page.getByRole('button', { name: '设置', exact: true }).click(); await page.getByLabel('语言', { exact: true }).selectOption('en'); await page.getByLabel('Font size', { exact: true }).selectOption('24'); await page.getByRole('button', { name: 'Black', exact: true }).click(); await page.keyboard.press('Escape');
 await page.getByRole('button', { name: 'New chat', exact: false }).click(); scenario = 'normal'; await page.getByLabel('Message', { exact: true }).fill(demoProblem.en); await page.getByRole('button', { name: 'Send message', exact: true }).click(); await expect(page.getByRole('button', { name: 'Stop generating', exact: true })).toHaveCount(0, { timeout: 45000 });
 await page.setViewportSize({ width: 430, height: 900 }); await page.locator('.message-scroll').evaluate(el => el.scrollTop = 0); await shot('07-english-black-24px-narrow');
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 await page.getByText('Complete model', { exact: true }).click(); await expect(page.locator('.automation-model .katex-html')).toBeVisible();
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 checks.push('English 24px black theme and narrow-screen model without page overflow');
 expect(errors).toEqual([]); expect(budgets.filter(b => b.stage === 'explanation').every(b => b.maxTokens === 768)).toBe(true);
 fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify({ status: 'passed', kind: 'mock_provider_real_highs_software_QA', checks, plans, explanations, budgets, errors }, null, 2)); console.log(JSON.stringify({ directory, checks }));
} catch (e) { await shot('failure').catch(() => {}); fs.writeFileSync(path.join(directory, 'failure.txt'), e.stack); console.error(directory, e); process.exitCode = 1; }
finally { await browser.close(); await service.close(); }
