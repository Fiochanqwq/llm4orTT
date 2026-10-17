import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { chromium, expect } from '@playwright/test';
import { startServer } from '../server/http.mjs';

// Offline regression: replay stored provider output, never send a live request.
const originalFile = process.env.REPLAY_WORKSPACE || 'C:/Users/30351/AppData/Local/FYPPPPP/workspace/workspace.json';
const original = fs.readFileSync(originalFile, 'utf8'), workspace = JSON.parse(original);
const examples = workspace.conversations.flatMap(c => c.messages.map((m, i) => ({ c, m, i })))
  .filter(({ m }) => m.provider === 'deepseek' && m.error?.includes('唯一有效') && m.automation?.plan?.calls?.length === 0 && m.automation.plan.text?.trim().startsWith('{'));
assert.ok(examples.length > 0, 'No saved incident found');
const directory = path.resolve('qa', 'json-incident-replay-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
let sample, plannerCalls = 0;
const service = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async value => value, unprotect: async value => value },
  planner: async () => { plannerCalls++; return structuredClone(sample.m.automation.plan); },
  generator: async function* () { throw Error('No explanation request expected for infeasibility'); }
});
await service.store.configure('deepseek', { region: 'global', model: 'deepseek-flash', apiKey: 'offline-fixture-only', maxTokens: 4096 });
service.store.data.preferences.provider = 'deepseek'; service.store.save();
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1360, height: 950 } });
const results = [];
try {
  for (sample of examples) {
    const c = service.store.create(); c.title = '离线回放 ' + (results.length + 1);
    assert.equal(sample.c.messages[sample.i - 1].role, 'user');
    c.messages = structuredClone(sample.c.messages.slice(0, sample.i - 1)); service.store.touch(c);
    await page.goto(service.origin + '/#token=' + service.token);
    await page.reload();
    await page.getByRole('button', { name: c.title, exact: true }).click();
    await page.getByLabel('消息', { exact: true }).fill(sample.c.messages[sample.i - 1].content);
    await page.getByRole('button', { name: '发送消息', exact: true }).click();
    await expect(page.getByRole('button', { name: '停止生成', exact: true })).toHaveCount(0, { timeout: 45000 });
    const answer = c.messages.at(-1);
    assert.equal(answer.automation.submissionSource, 'json_content');
    assert.equal(answer.automation.result.status, 'infeasible'); assert.equal(answer.automation.result.invoked, true);
    assert.equal(answer.automation.plan.calls.length, 0); assert.equal(answer.automation.task.clarifications, 1);
    await page.locator('.automation-details').last().locator('summary').click();
    await expect(page.locator('.automation-details').last()).toContainText('JSON 兼容提交');
    await page.screenshot({ path: path.join(directory, 'replay-' + (results.length + 1) + '.png') });
    results.push({ originalMessageId: sample.m.id, originalStatus: sample.m.status, replayStatus: answer.status, solverStatus: answer.automation.result.status, runId: answer.automation.runId, submissionSource: answer.automation.submissionSource });
  }
  assert.equal(fs.readFileSync(originalFile, 'utf8'), original, 'Original workspace changed during replay');
  const report = { status: 'passed', kind: 'offline_saved_response_replay_not_new_model_experiment', liveModelRequests: 0, plannerReplays: plannerCalls, results };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ ...report, directory }));
} finally { await browser.close(); await service.close(); }
