import { _electron, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const directory=path.resolve('qa','desktop-v07-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(directory,{recursive:true});
const app=await _electron.launch({executablePath:path.resolve('release/0.7.0/win-unpacked/llm4orOvO.exe'),env:{...process.env,FYPPPPP_DATA_DIR:path.join(directory,'launcher-workspace'),FYPPPPP_PORT:'43138',FYPPPPP_QA:'1'}});
try{
 const result=await app.evaluate(async({app},directory)=>{
  const load=process.mainModule.require.bind(process.mainModule),path=load('node:path'),root=app.getAppPath();
  const {startServer}=load(path.join(root,'server/http.mjs'));
  const {targetKeys}=load(path.join(root,'shared/task-contract.mjs'));
  const model={format:'llm4orovo.lp.v1',name:'Packaged_Fertilizer',sense:'minimize',variables:['C','Y'].map(name=>({name,type:'continuous',lower:0,upper:null})),objective:{C:2,Y:3},constraints:[{name:'n',terms:{C:1.5,Y:5},sense:'>=',rhs:5},{name:'v',terms:{C:3,Y:1},sense:'>=',rhs:8}]};
  let calls=0,explanations=0;
  const service=await startServer({directory,staticDir:path.join(root,'dist'),port:0,secretVault:{protect:async x=>'qa:'+x,unprotect:async x=>x.slice(3)},planner:async(config,messages)=>{
   calls++;const input=JSON.parse(messages[0].content),source=input.originalMessages[0];let args;
   if(config.tool.name==='review_optimization')args={review_json:JSON.stringify({status:'no_issue_found',diagnostics:[],factIds:['f','b'],targetIds:targetKeys(model),budgetApplicability:'supported'})};
   else {const contract={format:'llm4orovo.submission.v2',modelPurpose:'budget_threshold_base',facts:['f','b'].map(id=>({id,kind:'requirement',sourceMessageId:source.id,sourceSpan:source.content,entityRefs:[],unit:'USD',value:null,status:id==='b'?'unresolved':'active',supersedes:[]})),bindings:[...['variable','objective','constraint'].map(targetKind=>({factIds:['f'],targetKind,targetIds:targetKind==='constraint'?['n','v']:['C','Y'],disposition:'encoded'})),{factIds:['b'],targetKind:'gap',targetIds:['g'],disposition:'deferred_to_budget_gate'}],gaps:[{id:'g',factId:'b',kind:'budget',status:'open',questionId:null}],budget:{factId:'b',gapId:'g',lower:5,upper:6,unit:'USD',costTerms:model.objective,confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true}};args={action:'solve',model_json:JSON.stringify(model),contract_json:JSON.stringify(contract),message:'Packaged mock model response',questions:[]};}
   return {calls:[],text:JSON.stringify(args),usage:{input:10,output:20},rawUsage:{fixture:true},truncated:false};
  },generator:async function*(){explanations++;yield{text:'Unexpected interpretation'};}});
  try{
   await service.store.configure('deepseek',{region:'global',model:'qa-model',apiKey:'qa-only',maxTokens:12000});
   const c=service.store.create();const send=async(message)=>{const response=await fetch(service.origin+'/api/chat',{method:'POST',headers:{'content-type':'application/json','x-fyppppp-token':service.token},body:JSON.stringify({conversationId:c.id,provider:'deepseek',message})});await response.text();return c.messages.at(-1);};
   const first=await send('Packaged software fixture: fully specified fertilizer minimization with fixed hidden budget in [5,6].');
   const second=await send('已批准且固定的预算为 5 美元，不能追加。');
   const exported=service.exports.create({conversationIds:[c.id],format:'zip'});
   return {first:first.automation.stage,firstOutcome:first.automation.resultContract.taskOutcome,second:second.automation.resultContract.budgetDecision,reused:second.automation.resultContract.evidenceReused,calls,explanations,solves:service.solver.list().length,displayValid:second.automation.resultContract.displayValidation.feasible,transport:first.automation.submissionSource,archiveComplete:exported.manifest.complete,providerNetworkCalls:0};
  }finally{await service.close();}
 },path.join(directory,'research-workspace'));
 expect(result).toEqual({first:'clarification',firstOutcome:'awaiting_answer',second:'all_infeasible',reused:true,calls:2,explanations:0,solves:1,displayValid:true,transport:'json_content',archiveComplete:true,providerNetworkCalls:0});
 fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({directory,result}));
}finally{await app.close();}
