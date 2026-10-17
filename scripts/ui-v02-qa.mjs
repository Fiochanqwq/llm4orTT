import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
const directory = path.resolve('qa', 'ui-v02-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
const server = await startServer({ directory: path.join(directory, 'fixture-data'), staticDir: path.resolve('dist'), port: 0,
  secretVault: { protect: async value => Buffer.from(value).toString('base64'), unprotect: async value => Buffer.from(value, 'base64').toString() },
  generator: async function* () { throw Object.assign(new Error('Mock authentication error'), { status: 401 }); }
});
server.store.data.preferences.chatMode = 'chat'; server.store.save();
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } }), page = await context.newPage(), checks = [], errors = [];
page.on('pageerror', error => errors.push(error.message));
const shot = name => page.screenshot({ path: path.join(directory, name + '.png'), fullPage: true });
const size = () => page.locator('.composer textarea').evaluate(element => getComputedStyle(element).fontSize);
try {
  await page.goto(server.origin + '/#token=' + server.token); await expect(page.locator('.brand')).toHaveText('llm4orOvO'); await expect(page).toHaveTitle('llm4orOvO');
  await expect.poll(size).toBe('18px'); await shot('01-chinese-home'); checks.push('renamed brand and title; default body font is 18px');
  await page.getByRole('button', { name: '设置', exact: true }).click(); await page.getByLabel('语言', { exact: true }).selectOption('en');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en'); await expect(page.getByRole('heading', { name: 'Appearance', exact: true })).toBeVisible();
  await page.getByLabel('Font size', { exact: true }).selectOption('24'); await expect.poll(size).toBe('24px');
  await shot('02-english-settings-24px'); checks.push('English settings and font selection apply immediately');
  const second = await context.newPage(); await second.goto(server.origin + '/#token=' + server.token); await expect(second.getByRole('heading', { name: 'New chat', exact: true })).toBeVisible();
  await expect.poll(() => second.locator('.composer textarea').evaluate(element => getComputedStyle(element).fontSize)).toBe('24px'); await second.close(); checks.push('second browser page reads saved language and font size');
  await page.getByRole('button', { name: 'API', exact: true }).click(); await page.locator('.provider-tabs').getByRole('button', { name: 'Qwen' }).click();
  await expect(page.getByLabel('Region', { exact: true }).locator('option').first()).toHaveText('Mainland China · Beijing');
  await expect(page.getByLabel('API key', { exact: true })).toBeVisible(); await expect(page.getByRole('button', { name: 'Test connection', exact: true })).toBeVisible();
  const interfaceText = await page.locator('.settings-dialog').innerText(); expect(interfaceText).not.toMatch(/[\u4e00-\u9fff]/);
  await shot('03-english-api'); checks.push('API labels, regions, actions and notes translated');
  await page.getByRole('button', { name: 'Appearance', exact: true }).click();
  await page.getByLabel('Font size', { exact: true }).selectOption('14'); await expect.poll(size).toBe('14px');
  await page.getByRole('button', { name: 'Increase font size', exact: true }).click(); await expect.poll(size).toBe('15px');
  await page.getByRole('button', { name: 'Reset', exact: true }).click(); await expect.poll(size).toBe('18px'); checks.push('font minimum, step control and reset');
  await page.getByLabel('Font size', { exact: true }).selectOption('24'); await expect.poll(size).toBe('24px');
  await page.setViewportSize({ width: 430, height: 850 }); await shot('04-narrow-english-settings');
  const noOverflow = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && [...document.querySelectorAll('.settings-body,.settings-sidebar')].every(element => element.scrollWidth <= element.clientWidth + 1));
  expect(await noOverflow()).toBe(true); checks.push('24px English appearance layout fits narrow screen');
  await page.getByRole('button', { name: 'API', exact: true }).click(); expect(await noOverflow()).toBe(true);
  await page.getByRole('button', { name: 'Close settings', exact: true }).click(); await shot('05-narrow-english-home');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.getByRole('button', { name: 'Settings', exact: true }).click(); await page.getByLabel('Font size', { exact: true }).selectOption('18'); await expect.poll(size).toBe('18px');
  await page.getByRole('button', { name: 'Close settings', exact: true }).click(); await page.reload(); await expect(page.getByRole('heading', { name: 'New chat', exact: true })).toBeVisible(); await expect.poll(size).toBe('18px'); await shot('06-english-home'); checks.push('preferences persist after reload');
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Keep this draft unchanged.');
  await page.getByRole('button', { name: 'Settings', exact: true }).click(); await page.getByLabel('Language', { exact: true }).selectOption('zh-CN'); await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN'); await page.getByRole('button', { name: '关闭设置', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '消息', exact: true })).toHaveValue('Keep this draft unchanged.'); checks.push('switch back to Chinese preserves draft');
  await page.getByRole('button', { name: '设置', exact: true }).click(); await page.getByLabel('语言', { exact: true }).selectOption('en');
  await page.getByRole('button', { name: 'API', exact: true }).click(); await page.getByPlaceholder('Enter API key').fill('qa-not-real'); await page.getByRole('button', { name: 'Save', exact: true }).click(); await expect(page.getByRole('status')).toHaveText('Saved');
  await page.getByRole('button', { name: 'Close settings', exact: true }).click(); await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.locator('.message-status')).toContainText('The API key is invalid'); checks.push('mock provider error is translated without changing chat content');
  expect(errors).toEqual([]);
  const report = { status: 'passed', kind: 'software_qa_only_no_provider_calls', checks, errors, directory };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
} catch (error) { await shot('failure'); fs.writeFileSync(path.join(directory, 'failure.txt'), error.stack || String(error)); console.error(directory, error); process.exitCode = 1; }
finally { await browser.close(); await server.close(); }
