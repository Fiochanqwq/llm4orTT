// Reopen saved QA data only; no model request or solver action.
import {chromium,expect} from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import {startServer} from '../server/http.mjs';
const directory=path.resolve(process.argv[2]),service=await startServer({directory:path.join(directory,'workspace'),staticDir:path.resolve('dist'),port:0,planner:async()=>{throw Error('Read-only visual QA');},generator:async function*(){throw Error('Read-only visual QA');}});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1280,height:1000},reducedMotion:'reduce'});await page.goto(service.origin+'/#token='+service.token);
 await page.locator('.conversation-title').first().click();await expect(page.locator('.research-answer').last()).toContainText('本次提供的实际预算 6 USD');
 await page.locator('.research-answer').last().scrollIntoViewIfNeeded();await expect(page.locator('.message').last()).toHaveCSS('opacity','1');
 await page.screenshot({path:path.join(directory,'05-actual-budget-settled.png'),fullPage:true,animations:'disabled'});
 const report={status:'passed',scope:'saved final answer after arrival animation',providerCalls:0,solverCalls:0,opacity:1,screenshot:'05-actual-budget-settled.png'};fs.writeFileSync(path.join(directory,'visual-recheck.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();await service.close();}
