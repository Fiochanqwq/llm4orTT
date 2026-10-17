import { _electron,expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const directory=path.resolve('qa','graduation-v075-desktop-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(directory,{recursive:true});
const version=JSON.parse(fs.readFileSync('package.json','utf8')).version;
const app=await _electron.launch({executablePath:path.resolve(`release/${version}/win-unpacked/llm4orOvO.exe`),env:{...process.env,FYPPPPP_DATA_DIR:path.join(directory,'launcher'),FYPPPPP_PORT:'43138',FYPPPPP_QA:'1'}});
try{
 const result=await app.evaluate(async({app},directory)=>{
  const load=process.mainModule.require.bind(process.mainModule),path=load('node:path'),root=app.getAppPath(),fs=load('node:fs');
  const {startServer}=load(path.join(root,'server/http.mjs'));
  const {compactVersion,compactReviewVersion}=load(path.join(root,'shared/compact-protocol.mjs'));
  const model={format:'llm4orovo.lp.v1',name:'Packaged_v075',sense:'minimize',variables:['C','Y'].map(name=>({name,type:'continuous',lower:0,upper:null})),objective:{C:2,Y:3},constraints:[{name:'n',terms:{C:1.5,Y:5},sense:'>=',rhs:5},{name:'v',terms:{C:3,Y:1},sense:'>=',rhs:8}]};
  let calls=0,explanations=0;
  const service=await startServer({directory,staticDir:path.join(root,'dist'),port:0,secretVault:{protect:async x=>'qa:'+x,unprotect:async x=>x.slice(3)},planner:async(config,input)=>{
   calls++;const envelope=JSON.parse(input[0].content),data=envelope.context||envelope;let args;
   if(config.tool.name==='review_optimization')args={review_json:JSON.stringify({format:compactReviewVersion,status:'no_issue_found',checks:{requirements:'checked',mathematics:'checked',amendments:'not_applicable',budget:'checked'},diagnostics:[],budgetApplicability:'supported'})};
   else if(config.tool.parameters.properties.contract_json){args={action:'solve',model_json:JSON.stringify(model),message:'最低成本基准模型',questions:[],entities:[{variable:'C',label:'肥料 C',unit:'千克',sources:['s1']}],contract_json:JSON.stringify({format:compactVersion,requirements:[{statement:'Explicit cost and demand requirements',sources:[envelope.issue?'s1':'s999'],targets:[{kind:'variable',name:'C'},{kind:'variable',name:'Y'},{kind:'objective'},{kind:'constraint',name:'n'},{kind:'constraint',name:'v'}]}],missing:[],budget:{lower:5,upper:6,unit:'USD',sources:['s1'],confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true}})};}
   else if(!data.toolEvidence.length)args={action:'solve',model_json:JSON.stringify(model),message:'Base cost',questions:[]};
   else if(data.originalMessages.length===1)args={action:'clarify',model_json:'',message:'Actual budget needed',questions:[{question:'What is the actual approved budget?'}]};
   else {const r=data.toolEvidence[0];args={action:'final',model_json:'',message:`Budget 6 USD covers minimum cost ${r.objective} USD.`,questions:[],final:{status:'optimal',evidence:['r1'],values:r.values,objective:r.objective}};}
   return {calls:[],text:JSON.stringify(args),usage:{input:10,output:20},truncated:false};
  },generator:async function*(){explanations++;throw Error('Unexpected generator');}});
  try{
   await service.store.configure('deepseek',{region:'global',model:'qa-injected',apiKey:'qa-only',maxTokens:16000});service.store.data.preferences.methodPreset='full';
   const send=async(c,message)=>{const response=await fetch(service.origin+'/api/chat',{method:'POST',headers:{'content-type':'application/json','x-fyppppp-token':service.token},body:JSON.stringify({conversationId:c.id,provider:'deepseek',message})});if(!response.ok)throw Error(await response.text());await response.text();return c.messages.at(-1);};
   const prompt='C and Y are nonnegative continuous kg, minimize 2C+3Y USD, subject to 1.5C+5Y>=5 and 3C+Y>=8. Fixed approved budget is in [5,6] USD, cannot increase, with no other costs or conditions.';
   const draft=await service.experiments.create({cases:[{id:'packaged-check',prompt}],presets:['generic','full'],provider:'deepseek',requestCap:8});if(draft.sourceSnapshot.appVersion!=='0.7.5'||!draft.sourceSnapshot.builtFrom)throw Error('Packaged execution snapshot missing');
   const c=service.store.create(),first=await send(c,prompt),wrong=await send(c,'6 EUR'),last=await send(c,'6 USD');
   const full={first:first.automation.stage,transport:first.automation.submissionSource,wrongUnit:wrong.automation.decision.code,final:last.automation.stage,calls:last.automation.task.calls,corrections:last.automation.task.protocolCorrections,solves:last.automation.task.solves,reused:last.automation.resultContract.evidenceReused,budget:last.automation.resultContract.budgetDecision,entities:last.automation.resultContract.entities,content:last.content};
   const repeated=await send(c,'6 USD');full.duplicate=repeated.automation.decision.code;
   service.store.data.preferences.methodPreset='generic';const g=service.store.create();await send(g,prompt);const genericLast=await send(g,'Budget is 6 USD; no additions.');
   const generic={stage:genericLast.automation.stage,calls:genericLast.automation.task.calls,solves:genericLast.automation.task.solves,semantic:genericLast.automation.methods.semanticReview,budget:genericLast.automation.methods.budgetRelevance,status:genericLast.automation.publicOutcome.status};
   const exported=service.exports.create({conversationIds:[c.id,g.id],format:'json'}),entries=service.exports.tickets.get(exported.url.split('/').at(-1)).entries;
   const archive=entries.map(e=>fs.readFileSync(e.path,'utf8')).join('\n');
   return {packageSnapshotVersion:draft.sourceSnapshot.appVersion,packageSourceHash:draft.sourceSnapshot.builtFrom.sha256,full,generic,totalPlannerCalls:calls,realSolves:service.solver.list().length,explanations,providerNetworkCalls:0,exportHasV4:archive.includes(compactVersion),credentialLeak:archive.includes('qa-only'),bundledCLI:fs.existsSync(path.join(root,'server/experiments-cli.mjs'))};
  }finally{await service.close();}
 },path.join(directory,'research'));
 expect(result.full).toMatchObject({first:'clarification',transport:'json_content',wrongUnit:'budget_unit_conflict',final:'complete',calls:3,corrections:1,solves:1,reused:true,budget:'all_feasible',duplicate:'no_new_information'});
 expect(result.full.content).toContain('6 USD');expect(result.full.content).not.toContain('throughout');expect(result.full.entities[0].label).toBe('肥料 C');
 expect(result.generic).toEqual({stage:'complete',calls:3,solves:1,semantic:'not_run',budget:'not_run',status:'optimal'});
 expect(result).toMatchObject({totalPlannerCalls:6,realSolves:2,explanations:0,providerNetworkCalls:0,exportHasV4:true,credentialLeak:false,bundledCLI:true});
 const report={status:'passed',checks:4,version,...result};fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({directory,...report}));
}finally{await app.close();}
