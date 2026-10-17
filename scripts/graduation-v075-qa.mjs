import { chromium,expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { startServer } from '../server/http.mjs';
import { compactPlan,compactReviewed,fertilizerModel } from './fixtures/compact-v074.mjs';
const directory=path.resolve('qa','graduation-v075-integration-'+new Date().toISOString().replace(/[:.]/g,'-')),workspace=path.join(directory,'workspace');fs.mkdirSync(directory,{recursive:true});
const prompt='C、Y 为非负连续变量，单位千克，最低成本 2C+3Y 美元；需求 1.5C+5Y≥5 和 3C+Y≥8，无其他费用或约束。已批准且固定的预算在 [5,6] 美元，不能追加。';
const checks=[],errors=[];let calls=0;
const service=await startServer({directory:workspace,staticDir:path.resolve('dist'),port:0,secretVault:{protect:async x=>'qa:'+x,unprotect:async x=>x.slice(3)},planner:async(config,input)=>{
  calls++;const envelope=JSON.parse(input[0].content),data=envelope.context||envelope;
  if(config.tool.name==='review_optimization')return compactReviewed();
  if(config.tool.parameters.properties.contract_json)return compactPlan(data,{badSource:data.originalMessages[0].content.includes('注入引用')&&!envelope.issue,entities:true});
  const tool=data.toolEvidence?.[0];let args;
  if(!tool)args={action:'solve',model_json:JSON.stringify(fertilizerModel),message:'求取最低成本。',questions:[]};
  else if(data.originalMessages.length===1)args={action:'clarify',model_json:'',message:'需要判断是否能负担。',questions:[{question:'请告诉我实际批准了多少钱？'}]};
  else {const amount=Number(data.originalMessages.at(-1).content.match(/预算为\s*([\d.]+)/)?.[1]);if(!Number.isFinite(amount))throw Error('Fixture requires actual disclosed budget');args={action:'final',model_json:'',message:`根据实际预算 ${amount} 美元和最低成本 ${tool.objective} 美元，${amount>=tool.objective?'可负担':'预算不足'}。`,questions:[],final:{status:amount>=tool.objective?'optimal':'infeasible',evidence:['r1'],values:amount>=tool.objective?tool.values:null,objective:amount>=tool.objective?tool.objective:null}};}
  return {calls:[{name:'submit_optimization',arguments:args}],usage:{input:10,output:20}};
},generator:async function*(){throw Error('Unexpected provider generator');}});
await service.store.configure('deepseek',{apiKey:'qa-only',region:'global',model:'qa-injected',maxTokens:16000});service.store.data.preferences.provider='deepseek';service.store.data.preferences.methodPreset='full';service.store.save();
fs.writeFileSync(path.join(workspace,'runtime.json'),JSON.stringify({origin:service.origin,token:service.token,pid:process.pid}));
const request=async(route,body)=>{const r=await fetch(service.origin+route,{method:body?'POST':'GET',headers:{'x-fyppppp-token':service.token,...(body?{'content-type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});if(!r.ok)throw Error(await r.text());return r;};
const send=async(c,message)=>{await(await request('/api/chat',{conversationId:c.id,provider:'deepseek',message})).text();return c.messages.at(-1);};
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true}),page=await browser.newPage({viewport:{width:1280,height:1000}});page.on('pageerror',e=>errors.push(e.message));
try{
  await page.goto(service.origin+'/#token='+service.token);await page.getByLabel('消息',{exact:true}).fill(prompt+'（软件测试：注入引用故障）');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await expect(page.locator('.clarification-card')).toBeVisible({timeout:60000});expect(calls).toBe(3);await page.screenshot({path:path.join(directory,'01-question.png'),fullPage:true});
  await page.locator('.clarification-card').getByLabel('你的答复').fill('6 EUR');await page.locator('.clarification-card').getByRole('button',{name:'提交答复',exact:true}).click();await expect(page.locator('.research-answer').last()).toContainText('预算单位与原条件不一致');expect(calls).toBe(3);
  const q=page.locator('.clarification-card').last();await q.getByLabel('你的答复').fill('6 USD');await q.getByRole('button',{name:'提交答复',exact:true}).click();await expect(page.locator('.research-answer').last()).toContainText('本次提供的实际预算 6 USD');await expect(page.locator('.research-answer').last()).toContainText('肥料 C');expect(calls).toBe(3);
  await page.screenshot({path:path.join(directory,'02-actual-budget.png'),fullPage:true});checks.push('current compact protocol corrects one reference, actual HiGHS solves, unit typo recovers without calls, exact budget wording and entity units displayed');
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出当前对话为 JSON',exact:true}).click();await(await download).saveAs(path.join(directory,'conversation.json'));const exported=fs.readFileSync(path.join(directory,'conversation.json'),'utf8');expect(exported).toContain('llm4orovo.submission.v4');expect(exported).not.toContain('qa-only');checks.push('conversation JSON preserves raw compact responses and evidence without credentials');
  const card=amount=>({hidden_fixed_budget:amount,unit:'USD',confirmedFixed:true});
  const reference=amount=>({version:'qa-reference',verified:true,provenance:'Independent fixed QA mathematics',status:amount===6?'optimal':'infeasible',model:{...fertilizerModel,constraints:[...fertilizerModel.constraints,{name:'budget',terms:fertilizerModel.objective,sense:'<=',rhs:amount}]},objective:amount===6?158/27:null,requiredDisclosures:['amount'],certificate:amount===5?'158/27 > 5':null});
  const config={title:'CLI paired software check',cases:[5,6].map(amount=>({id:'case'+amount,baseId:'fertilizer',prompt,privateCard:card(amount),reference:reference(amount)})),presets:['generic','full'],repeats:1,requestCap:16,provider:'deepseek',language:'zh-CN'};
  const file=path.join(directory,'cli.json');fs.writeFileSync(file,JSON.stringify(config));
  const prepared=await promisify(execFile)(process.execPath,['scripts/run-experiments.mjs','create','--config',file,'--data',workspace],{cwd:process.cwd(),windowsHide:true,timeout:30000});const frozen=JSON.parse(prepared.stdout);expect(frozen.status).toBe('draft');expect(frozen.requestCount).toBe(0);expect(frozen.sourceSnapshot.appVersion).toBe('0.7.5');fs.writeFileSync(path.join(directory,'created-manifest.json'),prepared.stdout);
  const cli=await promisify(execFile)(process.execPath,['scripts/run-experiments.mjs','start','--batch',frozen.id,'--data',workspace],{cwd:process.cwd(),windowsHide:true,timeout:90000});fs.writeFileSync(path.join(directory,'cli.log'),cli.stdout);
  const batch=service.experiments.list().find(b=>b.title===config.title),runs=service.experiments.batches.get(batch.id).runs.map(meta=>service.experiments.run(meta.id));
  expect(runs.length).toBe(4);expect(runs.every(r=>r.status==='complete'&&r.score.independent.verdict==='correct')).toBe(true);expect(runs.every(r=>r.entry==='cli')).toBe(true);checks.push('CLI runs four paired trajectories through the existing service; both methods get identical factual replies and independently correct scores');
  const summary=service.experiments.summary(batch.id);expect(summary.methods.map(m=>m.correct)).toEqual([2,2]);
  await promisify(execFile)(process.execPath,['scripts/run-experiments.mjs','export','--batch',batch.id,'--data',workspace,'--format','jsonl','--output',path.join(directory,'analysis.jsonl')],{cwd:process.cwd(),windowsHide:true,timeout:30000});
  const rows=fs.readFileSync(path.join(directory,'analysis.jsonl'),'utf8').trim().split(/\r?\n/).map(JSON.parse).filter(r=>r.kind==='run_summary');expect(rows.length).toBe(4);expect(rows.every(r=>r.score.statusAgreement===true&&r.score.originalTaskStatus===r.score.independent.outcome.status&&r.score.solverStatus==='optimal'&&r.sourceSnapshot.appVersion==='0.7.5')).toBe(true);expect(rows.reduce((n,r)=>n+r.calls,0)).toBe(10);expect(rows.every(r=>r.runId&&r.scorerVersion&&r.entry==='cli')).toBe(true);checks.push('analysis JSONL reconciles every run, ten injected requests, method versions and scores');
  const c=service.store.create();await send(c,prompt);const reply=runs.find(r=>r.caseId==='case6'&&r.preset==='full').events.find(e=>e.state==='controller_reply').content;await send(c,reply);
  const flow=c.messages.at(-1).automation,batchFlow=runs.find(r=>r.caseId==='case6'&&r.preset==='full').conversation.messages.at(-1).automation;
  expect({calls:flow.task.calls,solves:flow.task.solves,decision:flow.resultContract.budgetDecision,model:flow.result.model}).toEqual({calls:batchFlow.task.calls,solves:batchFlow.task.solves,decision:batchFlow.resultContract.budgetDecision,model:batchFlow.result.model});checks.push('chat supplied the same answer and CLI produce matching requests/solve count/mathematics/termination under fixed responses');
  await page.getByRole('button',{name:'实验工作台',exact:true}).click();await page.locator('.experiment-history button').filter({hasText:config.title}).click();await expect(page.locator('.run-list button')).toHaveCount(4);await page.locator('.run-list button').first().click();await expect(page.locator('.experiment-run')).toContainText('流程结束');await page.screenshot({path:path.join(directory,'03-paired-results.png'),fullPage:true});
  for(const width of [1280,768,390]){await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:path.join(directory,`04-layout-${width}.png`),fullPage:true});}
  expect(errors).toEqual([]);checks.push('workbench displays CLI results; 1280/768/390 widths have no horizontal overflow');
  const report={checks,errors,injectedPlannerCalls:calls,providerNetworkCalls:0,realSolverRuns:service.solver.list().length,pairedSoftwareTrajectories:runs.length,summary};fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({directory,...report}));
}finally{await browser.close();await service.close();}
