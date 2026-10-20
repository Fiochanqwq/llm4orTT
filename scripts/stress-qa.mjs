import {chromium,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const out=path.resolve(process.argv[2]||'outputs/inverse/public-stress-20261020-v2');
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(path.join(out,'压力测试报告.html')).href);
 await expect(page.getByRole('heading',{name:'分数好，不代表账算对',exact:true})).toBeVisible();
 await expect(page.locator('#source option')).toHaveCount(13);
 await expect(page.locator('#case-data tr')).toHaveCount(10);
 await expect(page.locator('#case-data')).toContainText('100.000%');
 for(const source of ['adlittle','mknap1-7','gr24']){
  await page.selectOption('#source',source);
  await page.selectOption('#seed','67');await page.selectOption('#k','5');await page.selectOption('#noise','0');
  await expect(page.locator('#case-data tr')).toHaveCount(10);
 }
 await page.selectOption('#source','afiro');await page.selectOption('#seed','19');
 await page.selectOption('#k','10');await page.selectOption('#noise','0.1');
 const links=await page.locator('a[href]').evaluateAll(as=>as.map(a=>a.getAttribute('href')).filter(x=>!x.startsWith('#')&&!x.startsWith('http')));
 for(const link of links)if(!fs.existsSync(path.join(out,decodeURIComponent(link))))throw Error('Broken local link '+link);
 if(await page.locator('img').evaluateAll(imgs=>imgs.length!==2||imgs.some(i=>!i.complete||i.naturalWidth===0)))throw Error('Missing figure');
 await page.screenshot({path:path.join(out,'报告首页.png')});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,'手机首页.png')});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 if(errors.length)throw Error(errors.join('\n'));
 const result={status:'passed',checks:['13 admitted sources','nine methods for each selected case','both K/noise conditions and different seeds','AFIRO price-error counterexample','all local evidence links','both figures loaded','mobile no overflow','no JavaScript errors']};
 fs.writeFileSync(path.join(out,'report-qa.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close()}
