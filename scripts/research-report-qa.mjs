import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const out=path.resolve('outputs/inverse/pilot-20261019-v3');
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(path.join(out,'实验报告.html')).href);
 await expect(page.getByRole('heading',{name:'先读工作日志，再从历史安排学规则'})).toBeVisible();
 await expect(page.locator('.barrow')).toHaveCount(4);
 const before=await page.locator('#bars').innerText();
 await page.locator('#k').selectOption('20');await page.locator('#noise').selectOption('0');
 const after=await page.locator('#bars').innerText();
 if(before===after)throw Error('Filters did not change data');
 await expect(page.locator('#bars')).toContainText('(6/6)');
 await page.locator('#k').selectOption('all');await page.locator('#noise').selectOption('all');
 await page.screenshot({path:path.join(out,'报告预览.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,'手机预览.png'),fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 if(overflow||errors.length)throw Error(JSON.stringify({overflow,errors}));
 const result={status:'passed',checks:['actual report data','four methods','K and noise filters','desktop layout','mobile layout','no page errors']};
 fs.writeFileSync(path.join(out,'report-qa.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close()}
