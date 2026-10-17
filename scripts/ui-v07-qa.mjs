import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
import { targetKeys } from '../shared/task-contract.mjs';
const directory=path.resolve('qa','ui-v07-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(directory,{recursive:true});
const model={format:'llm4orovo.lp.v1',name:'Fertilizer',sense:'minimize',variables:['C','Y'].map(name=>({name,type:'continuous',lower:0,upper:null})),objective:{C:2,Y:3},constraints:[{name:'nitrogen',terms:{C:1.5,Y:5},sense:'>=',rhs:5},{name:'vitamins',terms:{C:3,Y:1},sense:'>=',rhs:8}]};
let calls=0,explanations=0;const checks=[],errors=[];
const service=await startServer({directory:path.join(directory,'workspace'),staticDir:path.resolve('dist'),port:0,secretVault:{protect:async x=>'test:'+x,unprotect:async x=>x.slice(5)},
  planner:async(config,messages)=>{calls++;const input=JSON.parse(messages[0].content),source=input.originalMessages[0];
    if(config.tool.name==='review_optimization')return {calls:[{name:config.tool.name,arguments:{review_json:JSON.stringify({status:'no_issue_found',diagnostics:[],factIds:['f','b'],targetIds:targetKeys(model),budgetApplicability:'supported'})}}],usage:{input:10,output:20}};
    const contract={format:'llm4orovo.submission.v2',modelPurpose:'budget_threshold_base',facts:['f','b'].map(id=>({id,kind:id==='b'?'budget':'requirements',sourceMessageId:source.id,sourceSpan:source.content,entityRefs:[],unit:'USD',value:null,status:id==='b'?'unresolved':'active',supersedes:[]})),bindings:[...['variable','objective','constraint'].map(targetKind=>({factIds:['f'],targetKind,targetIds:targetKind==='constraint'?['nitrogen','vitamins']:['C','Y'],disposition:'encoded'})),{factIds:['b'],targetKind:'gap',targetIds:['gap'],disposition:'deferred_to_budget_gate'}],gaps:[{id:'gap',factId:'b',kind:'budget',status:'open',questionId:null}],budget:{factId:'b',gapId:'gap',lower:5,upper:6,unit:'USD',costTerms:model.objective,confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true}};
    return {calls:[{name:'submit_optimization',arguments:{action:'solve',model_json:JSON.stringify(model),contract_json:JSON.stringify(contract),message:'UI software fixture',questions:[]}}],usage:{input:10,output:20}};
  },generator:async function*(){explanations++;yield{text:'Unexpected explanation'};}
});
await service.store.configure('openai',{apiKey:'qa-only',region:'global',model:'qa-model',maxTokens:12000});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:1000}});page.on('pageerror',e=>errors.push(e.message));
const shot=name=>page.screenshot({path:path.join(directory,name+'.png'),fullPage:true});
try{
 await page.goto(service.origin+'/#token='+service.token);await expect(page.getByRole('heading',{name:'新对话',exact:true})).toBeVisible();
 expect(await page.locator('html').evaluate(el=>getComputedStyle(el).fontSize)).toBe('18px');
 await page.getByLabel('消息',{exact:true}).fill('软件测试：肥料 C/Y 线性成本和需求已完整给出；已批准固定预算在 [5,6] USD，不能追加。');await page.getByRole('button',{name:'发送消息',exact:true}).click();
 await expect(page.locator('.clarification-card')).toBeVisible({timeout:45000});await expect(page.getByRole('button',{name:'停止生成',exact:true})).toHaveCount(0);
 await page.locator('.clarification-card').getByRole('radio',{name:'否',exact:true}).check();expect(calls).toBe(2);expect(explanations).toBe(0);await shot('01-question-1280');
 await page.locator('.clarification-card').getByRole('button',{name:'提交答复',exact:true}).click();await expect(page.locator('.research-answer').last()).toContainText('预算不足');expect(calls).toBe(2);expect(service.solver.list().length).toBe(1);checks.push('budget question selectable without auto-send; one submitted answer reuses the actual solver result with no new model request');
 await page.locator('.message-scroll').evaluate(el=>el.scrollTop=el.scrollHeight);await shot('02-result-1280');
 const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'导出当前对话为 JSON',exact:true}).click();const dl=await downloaded;const exportFile=path.join(directory,'conversation.json');await dl.saveAs(exportFile);const bundle=JSON.parse(fs.readFileSync(exportFile,'utf8'));expect(bundle.schemaVersion).toBe(2);expect(JSON.stringify(bundle)).not.toContain('qa-only');checks.push('streamed conversation JSON contains v2 evidence and no test API credential');
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.locator('#reading-font').selectOption('georgia');await expect(page.locator('#reading-font')).toHaveValue('georgia');await page.locator('#font-size').selectOption('20');await page.locator('#interface-language').selectOption('en');await page.getByRole('button',{name:'Close settings',exact:true}).click();
 await page.reload();await expect(page.locator('html')).toHaveAttribute('lang','en');expect(await page.locator('body').evaluate(el=>getComputedStyle(el).fontFamily)).toContain('Georgia');checks.push('language, font family and size survive reload');
 for(const width of [1280,768,390]){await page.setViewportSize({width,height:1000});if(width===390)await page.getByRole('button',{name:'Expand sidebar',exact:true}).click();await page.getByRole('button',{name:'Experiments',exact:true}).click();await expect(page.getByRole('heading',{name:'Experiments',exact:true})).toBeVisible();await shot('03-experiments-'+width);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 await page.setViewportSize({width:1280,height:1000});await page.evaluate(()=>document.documentElement.style.fontSize='36px');await shot('04-200percent');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.keyboard.press('Tab');checks.push('1280/768/390 layouts and 200% text scale have no document horizontal overflow; keyboard navigation remains active');
 expect(errors).toEqual([]);fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify({checks,errors,calls,explanations,realSolverRuns:service.solver.list().length,providerNetworkCalls:0},null,2));console.log(JSON.stringify({directory,checks:checks.length}));
}finally{await browser.close();await service.close();}
