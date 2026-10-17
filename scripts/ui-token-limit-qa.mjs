import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';

const directory = path.resolve('qa', 'ui-token-limit-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
const service = await startServer({ directory: path.join(directory, 'workspace'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async value => value, unprotect: async value => value },
  planner: async () => { throw Error('No provider requests in settings QA'); },
  generator: async function* () { throw Error('No provider requests in settings QA'); }
});
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1200, height: 850 } });
try {
  await page.goto(service.origin + '/#token=' + service.token);
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByRole('button', { name: 'API', exact: true }).click();
  await page.getByRole('button', { name: '高级设置', exact: true }).click();
  const field = page.getByLabel('输出上限', { exact: true });
  await expect(field).toHaveAttribute('max', '327680');
  await expect(field).toHaveValue('4096');
  await field.fill('327680');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('已保存');
  await expect(field).toHaveValue('327680');
  await page.screenshot({ path: path.join(directory, '327680-zh.png'), animations: 'disabled' });
  await page.reload();
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByRole('button', { name: 'API', exact: true }).click();
  await page.getByRole('button', { name: '高级设置', exact: true }).click();
  await expect(page.getByLabel('输出上限', { exact: true })).toHaveValue('327680');
  await page.getByRole('button', { name: '外观', exact: true }).click();
  await page.getByLabel('语言', { exact: true }).selectOption('en');
  await page.getByRole('button', { name: 'API', exact: true }).click();
  await expect(page.getByLabel('Output limit', { exact: true })).toHaveValue('327680');
  await expect(page.getByLabel('Output limit', { exact: true })).toHaveAttribute('max', '327680');
  const result = { status: 'passed', kind: 'settings_ui_mock_no_provider_requests', directory,
    checks: ['default remains 4096', '327680 is accepted and persisted after reload', 'English settings display the same limit', 'no provider request was made'] };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  fs.writeFileSync(path.join(directory, 'failure.txt'), error.stack || String(error));
  await page.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => {});
  console.error(directory, error); process.exitCode = 1;
} finally { await browser.close(); await service.close(); }
