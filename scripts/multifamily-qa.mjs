import {chromium,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const out=path.resolve(process.argv[2]||'outputs/inverse/multifamily-20261020-v1');
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(path.join(out,'跨题型报告.html')).href);
 await expect(page.getByRole('heading',{name:'跨题型实验：好结果与反例一起交账'})).toBeVisible();
 await expect(page.locator('#detail tbody tr')).toHaveCount(128);
 await page.selectOption('#family','tour');await page.selectOption('#method','text_sparse_io');
 await expect(page.locator('#detail tbody tr')).toHaveCount(5);
 await page.selectOption('#k','5');await page.selectOption('#noise','0');
 await expect(page.locator('#detail tbody tr')).toHaveCount(5);
 await page.selectOption('#family','relocation');await page.selectOption('#k','20');await page.selectOption('#noise','0.1');
 await expect(page.locator('#detail tbody tr')).toHaveCount(11);
 await expect(page.locator('#detail')).toContainText('44');
 const a=JSON.parse(fs.readFileSync(path.join(out,'analysis.json'),'utf8'));
 const expected=a.sourceSummaries.find(r=>r.id===44&&r.method==='text_sparse_io'&&r.K===20&&r.noise===.1);
 await expect(page.locator('#detail')).toContainText((expected.maximum*100).toFixed(3)+'%');
 for(const file of ['跨题型报告.html','paper.html']){
  await page.goto(pathToFileURL(path.join(out,file)).href);
  const links=await page.locator('a[href]').evaluateAll(as=>as.map(a=>a.getAttribute('href')).filter(x=>!x.startsWith('#')&&!x.startsWith('http')));
  if(links.some(x=>!fs.existsSync(path.join(out,decodeURIComponent(x)))))throw Error('Broken local links');
  if(await page.locator('img').evaluateAll(imgs=>imgs.length!==2||imgs.some(i=>!i.complete||i.naturalWidth===0)))throw Error('Missing figure');
 }
 await page.goto(pathToFileURL(path.join(out,'跨题型报告.html')).href);
 await page.screenshot({path:path.join(out,'报告首页.png')});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,'手机首页.png')});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 if(errors.length)throw Error(errors.join('\n'));
 const result={status:'passed',checks:['all128 primary source/method rows','5 tour and11 relocation source selectors','both K andnoise conditions','source44 worst seed retained','all local evidence links','all4 embedded figure uses loaded','mobile no page overflow','no JavaScript errors']};
 fs.writeFileSync(path.join(out,'report-qa.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close()}
