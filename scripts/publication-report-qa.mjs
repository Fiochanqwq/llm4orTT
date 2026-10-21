import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const out = path.resolve(process.argv[2]);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(path.join(out, '完整研究报告.html')).href);
  await expect(page.getByRole('heading', { name: '可靠性先于漂亮分数', exact: true })).toBeVisible();
  await expect(page.locator('section')).toHaveCount(7);
  await expect(page.locator('#comparison tbody tr:visible')).toHaveCount(12);
  await page.selectOption('#budget', '8');
  await expect(page.locator('#comparison tbody tr:visible')).toHaveCount(4);
  const visible = await page.locator('#comparison tbody tr:visible').evaluateAll(rows => rows.map(r => r.dataset.budget));
  if (visible.some(b => b !== '8')) throw Error('Budget filter changed the wrong rows');
  await page.selectOption('#budget', 'all');
  const links = await page.locator('a[href]').evaluateAll(nodes => nodes.map(n => n.getAttribute('href'))
    .filter(h => !h.startsWith('#') && !h.startsWith('https:')));
  for (const link of links) {
    if (!fs.existsSync(path.join(out, decodeURIComponent(link)))) throw Error('Broken local evidence link: ' + link);
  }
  if (await page.locator('img').evaluateAll(images => images.length !== 3 || images.some(i => !i.complete || !i.naturalWidth))) {
    throw Error('Missing scientific figure');
  }
  await page.screenshot({ path: path.join(out, '报告首页.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, '手机首页.png') });
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('Mobile horizontal overflow');
  if (errors.length) throw Error(errors.join('\n'));
  const result = {
    passed: true, sections: 7, comparisonRows: 12, figures: 3, localLinks: links.length,
    checks: ['Budget filtering', 'All local evidence links', 'Loaded figures', 'Mobile overflow', 'No JavaScript errors'],
  };
  fs.writeFileSync(path.join(out, 'report-qa.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
