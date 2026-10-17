import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server/http.mjs';
import { fixtureResponse } from './fixtures/protocol-v071.mjs';
const directory=path.resolve('qa','ui-v073-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(directory,{recursive:true});
let scenario='valid',calls=0;const checks=[],errors=[];
const service=await startServer({directory:path.join(directory,'workspace'),staticDir:path.resolve('dist'),port:0,secretVault:{protect:async x=>'qa:'+x,unprotect:async x=>x.slice(3)},planner:async(c,m)=>{calls++;return fixtureResponse(c,m,scenario);},generator:async function*(){throw Error('Unexpected generator');}});
await service.store.configure('deepseek',{apiKey:'qa-only',region:'global',model:'qa-model',maxTokens:12000});service.store.data.preferences.provider='deepseek';service.store.save();
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});const page=await browser.newPage({viewport:{width:1280,height:1000}});page.on('pageerror',e=>errors.push(e.message));
const shot=name=>page.screenshot({path:path.join(directory,name+'.png'),fullPage:true,animations:'disabled'});
try{
  await page.goto(service.origin+'/#token='+service.token);await expect(page.getByRole('heading',{name:'新对话',exact:true})).toBeVisible();
  await expect(page.getByLabel('允许一次提交纠正（计入 4 次调用）')).toBeChecked();
  await page.getByLabel('消息',{exact:true}).fill('软件测试：C、Y 为非负连续变量，最低成本 2C+3Y，需求 1.5C+5Y≥5 和 3C+Y≥8，无其他费用。已批准且固定预算在 [5,6] 美元。');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await expect(page.locator('.clarification-card')).toBeVisible({timeout:60000});expect(calls).toBe(3);await shot('01-corrected-question');
  await page.locator('.clarification-card').getByRole('radio',{name:'否',exact:true}).check();await page.locator('.clarification-card').getByRole('button',{name:'提交答复',exact:true}).click();await expect(page.locator('.research-answer').last()).toContainText('预算不足');expect(calls).toBe(3);expect(service.solver.list().length).toBe(1);
  const last=service.store.data.conversations[0].messages.at(-1).automation;expect(last.task.protocolCorrections).toBe(1);expect(last.resultContract.evidenceReused).toBe(true);checks.push('v3 JSON response -> one bounded reference correction -> actual HiGHS -> budget reply reuses evidence');
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出当前对话为 JSON',exact:true}).click();await(await download).saveAs(path.join(directory,'conversation.json'));const exported=fs.readFileSync(path.join(directory,'conversation.json'),'utf8');expect(exported).toContain('llm4orovo.submission.v3');expect(exported).toContain('protocolCorrections');expect(exported).not.toContain('qa-only');checks.push('export retains source/target catalogs and correction counts without credentials');
  await page.getByRole('button',{name:'新对话',exact:false}).click();
  await page.getByLabel('消息',{exact:true}).fill('软件测试：C、Y 为非负连续变量，最低成本 2C+3Y，需求 1.5C+5Y≥5 和 3C+Y≥8，无其他费用。已批准且固定预算在 [5,6] 美元。');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await expect(page.locator('.clarification-card')).toBeVisible({timeout:60000});const beforeConflict=calls,solvesBeforeConflict=service.solver.list().length;
  await page.getByLabel('消息',{exact:true}).fill('预算为5元');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await expect(page.locator('.research-answer').last()).toContainText('预算单位与原条件不一致');expect(calls).toBe(beforeConflict);expect(service.solver.list().length).toBe(solvesBeforeConflict);await shot('06-currency-conflict');checks.push('explicit currency mismatch pauses visibly without extra provider or solver calls');
  const currentQuestion=page.locator('.clarification-card').last();await expect(currentQuestion.getByRole('button',{name:'提交答复',exact:true})).toBeVisible();await currentQuestion.getByLabel('你的答复').fill('ＵＳＤ ５．５');await currentQuestion.getByRole('button',{name:'提交答复',exact:true}).click();
  await expect(page.locator('.research-answer').last()).toContainText('预算不足');await expect(page.locator('.research-answer').last()).toContainText('本次没有重新求解');expect(calls).toBe(beforeConflict);expect(service.solver.list().length).toBe(solvesBeforeConflict);await shot('07-corrected-answer-reused');checks.push('after a unit typo, the current question remains answerable and an equivalent full-width amount reuses evidence');
  for(const [name,value] of [['引用失败','bad-source'],['审核未解决','uncertain']]){
    scenario=value;const b=await service.experiments.create({title:name,cases:[{id:name,prompt:'软件测试：C、Y 非负实数，最小化 2C+3Y；1.5C+5Y≥5，3C+Y≥8。'}],provider:'deepseek',language:'zh-CN',presets:['full'],protocolCorrection:true});service.experiments.action(b.id,'start');while(service.experiments.working)await new Promise(r=>setTimeout(r,20));
    expect(service.experiments.batches.get(b.id).runs[0].status).toBe(value==='bad-source'?'failed':'partial');
  }
  await page.getByRole('button',{name:'实验工作台',exact:true}).click();await page.locator('.experiment-history button').filter({hasText:'引用失败'}).click();await page.locator('.run-list button').first().click();await expect(page.locator('.execution-issue')).toContainText('尚未调用求解器');await page.locator('.execution-issue summary').click();await expect(page.locator('.execution-issue')).toContainText('sourceRefs');await expect(page.getByRole('button',{name:'正确',exact:true})).toBeDisabled();await shot('02-failure-details');checks.push('failure reason visible without reading raw JSON; unfinished task cannot be scored correct');
  await page.locator('.experiment-history button').filter({hasText:'审核未解决'}).click();await expect(page.locator('.run-list')).toContainText('任务未完成');await page.getByText('按独立基题汇总（描述性结果）',{exact:true}).click();await expect(page.locator('.experiment-batch')).toContainText('任务完成正确率范围');await shot('03-partial-summary');checks.push('semantic uncertainty is partial, not complete; attempted-task denominator is visible');
  for(const width of [1280,768,390]){await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await shot('04-layout-'+width);}
  await page.setViewportSize({width:1280,height:1000});await page.evaluate(()=>document.documentElement.style.fontSize='36px');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await shot('05-large-text');checks.push('1280/768/390 and 200% text size fit viewport');
  expect(errors).toEqual([]);const report={kind:'injected_provider_ui_and_actual_solver',checks,errors,calls,providerNetworkCalls:0,realSolverRuns:service.solver.list().length};fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({directory,...report}));
}finally{await browser.close();await service.close();}
