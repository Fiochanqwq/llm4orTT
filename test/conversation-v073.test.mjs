import test from 'node:test';
import assert from 'node:assert/strict';
import { initializeMethods, executeV07, validateReply } from '../server/optimization-v07.mjs';
import { taskFor } from '../server/agent-policy.mjs';
import { sourceCatalog, targetCatalog } from '../shared/protocol-schema.mjs';
import { validateContract } from '../shared/task-contract.mjs';
import { numericalCheck, resultText } from '../shared/result-contract.mjs';
import { resolveBudgetReply } from '../server/budget-relevance.mjs';

const model={format:'llm4orovo.lp.v1',name:'Continuity',sense:'minimize',variables:[{name:'x',type:'continuous',lower:0,upper:null}],objective:{x:2},constraints:[{name:'need',terms:{x:1},sense:'>=',rhs:3}]};
const prompt='x 为非负实数，单价2美元，需求至少3，最小化费用。其他条件完整；已批准且固定预算在[5,7]美元。';
const fact=(id,source,extra={})=>({id,kind:'requirement',sourceRefs:[source],unit:'',value:null,supersedes:[],...extra});
const binding=(id,targets,disposition='encoded')=>({factIds:[id],targetRefs:targets,disposition,reason:disposition==='not_applicable'?'Retained pending formulation':''});
function ledger(messages,budget=false){const sources=sourceCatalog(messages),c={format:'llm4orovo.submission.v3',modelPurpose:budget?'budget_threshold_base':'final_task',facts:[fact('f',sources[0].id)],bindings:[binding('f',targetCatalog(model).filter(t=>t.required).map(t=>t.id))],gaps:[],budget:null};
  if(budget){c.facts.push(fact('b',sources.find(s=>s.text.includes('预算')).id));c.gaps=[{id:'gb',factId:'b',kind:'budget'}];c.bindings.push(binding('b',['gap:gb'],'deferred_to_budget_gate'));c.budget={factId:'b',gapId:'gb',lower:5,upper:7,unit:'USD',costTerms:model.objective,confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true};}return c;}
const submit=(c,m=model,questions=[])=>({calls:[{name:'submit_optimization',arguments:{action:questions.length?'clarify':'solve',message:'Local software fixture',model_json:questions.length?'':JSON.stringify(m),contract_json:JSON.stringify(c),questions}}],usage:{input:1,output:1}});
const reviewed=(c,m=model)=>({calls:[{name:'review_optimization',arguments:{review_json:JSON.stringify({format:'llm4orovo.review.v3',status:'no_issue_found',diagnostics:[],factIds:c.facts.map(f=>f.id),targetIds:targetCatalog(m).filter(t=>t.required).map(t=>t.id),gapIds:c.gaps.map(g=>g.id),budgetApplicability:c.budget?'supported':'not_applicable'})}}],usage:{input:1,output:1}});
function harness({planner,budget=false}={}){
  const config={id:'deepseek',model:'injected',language:'zh-CN',maxTokens:12000,modelingTokens:12000,protocolCorrection:false},conversation={messages:[]},records=new Map();let calls=0,solves=0;
  const solver={active:null,info:()=>({engines:{highs:{available:true}}}),start:({model:m})=>{solves++;const values={x:3},record={id:'r'+solves,engine:'highs',model:m,values,objective:6,bound:6,status:'optimal',provenance:{solverInvoked:true},check:numericalCheck(m,values)};records.set(record.id,record);return record;},get:id=>records.get(id),stop(){}};
  const send=async(content,replyTo)=>{
    const user={id:'u'+conversation.messages.length,role:'user',content,...(replyTo?{replyTo}:{})};conversation.messages.push(user);
    const answer={role:'assistant',content:'',provenance:{},automation:{task:taskFor(conversation,user,false),usage:{}}};initializeMethods(answer.automation,config,'highs','full');conversation.messages.push(answer);
    await executeV07({config,messages:conversation.messages.filter(m=>m.role==='user'),problem:content,engine:'highs',seconds:30,signal:new AbortController().signal,solver,answer,update(){},planner:async(conf,input)=>{calls++;const context=JSON.parse(input[0].content);if(planner)return planner({calls,conf,context,user});return conf.tool.name==='review_optimization'?reviewed(context.contract,context.model):submit(ledger(context.originalMessages,budget));}});
    return answer.automation;
  };
  return {send,conversation,records,calls:()=>calls,solves:()=>solves};
}
const to=q=>({taskId:q.taskId,questionId:q.id,gapId:q.gapId,factVersion:q.factVersion});
function missing(messages,resolved=[]){const root=sourceCatalog(messages)[0].id,c={format:'llm4orovo.submission.v3',modelPurpose:'final_task',facts:['a','b'].map(id=>fact(id,root)),bindings:[],gaps:[],budget:null};
  for(const id of ['a','b']){const supplied=resolved.find(r=>r.id===id);if(supplied){const source=sourceCatalog(messages).find(s=>s.messageId===supplied.messageId).id;c.facts.push(fact(id+'-answer',source,{supersedes:[id]}));c.bindings.push(binding(id+'-answer',['method:conditions'],'not_applicable'));}else{c.gaps.push({id:'g'+id,factId:id,kind:'quantity'});c.bindings.push(binding(id,['gap:g'+id],'pending_clarification'));}}
  if(!c.gaps.length)c.bindings[0]=binding('a-answer',targetCatalog(model).filter(t=>t.required).map(t=>t.id));return c;}
const questions=c=>c.gaps.map(g=>({gapId:g.id,field:g.factId,question:g.factId+'是多少？',impact:'确定模型条件'}));

test('budget answers accept common equivalent notation without extracting hypothetical or mixed conditions',()=>{
  const p={budget:{lower:5,upper:7,unit:'USD'},exact:{objective:'6'}};
  for(const answer of ['预算就是 5.5 美元，不能追加。','USD 5.5','５．５ 美元','5.5美金'])assert.equal(resolveBudgetReply(p,answer).value,5.5,answer);
  for(const answer of ['如果预算是5.5美元呢？','预算5.5美元，需求改成10','不确定是不是5.5美元','5美元或7美元','not 5 USD'])assert.equal(resolveBudgetReply(p,answer).status,'unparsed',answer);
});
test('currency correction after a rejected answer can still reuse the unchanged budget evidence',async()=>{
  const h=harness({budget:true});await h.send(prompt);const conflict=await h.send('预算为5元');assert.equal(conflict.stage,'paused');assert.ok(conflict.questions?.some(q=>q.status==='pending'));
  const fixed=await h.send('预算为5美元');assert.equal(fixed.resultContract?.evidenceReused,true);assert.equal(h.calls(),2);assert.equal(h.solves(),1);
});
test('identical short answers to different current questions are not duplicate instructions',async()=>{
  const h=harness({planner:({conf,context})=>{if(conf.tool.name==='review_optimization')return reviewed(context.contract);const ms=context.originalMessages,c=missing(ms,ms.slice(1).map((m,i)=>({id:i?'b':'a',messageId:m.id})));return submit(c,model,questions(c));}});
  const first=await h.send('需要补充a和b。'),second=await h.send('5',to(first.questions[0]));assert.equal(second.stage,'clarification');
  const final=await h.send('5',to(second.questions[0]));assert.equal(final.stage,'complete');assert.equal(h.calls(),4);assert.equal(h.solves(),1);
});
test('one answer may explicitly resolve multiple gaps even when sent from one question card',async()=>{
  const h=harness({planner:({conf,context})=>{if(conf.tool.name==='review_optimization')return reviewed(context.contract);const ms=context.originalMessages,c=missing(ms,ms.length>1?['a','b'].map(id=>({id,messageId:ms.at(-1).id})):[]);return submit(c,model,questions(c));}});
  const initial=await h.send('需要补充a和b。');const final=await h.send('a是5，b也是5。',to(initial.questions[0]));assert.equal(final.stage,'complete');assert.equal(final.gapResolutions.length,2);assert.equal(h.calls(),3);
});
test('multi-source supersession depends on evidence chronology, not sourceRefs array order',()=>{
  const messages=[{id:'old',role:'user',content:'原需求为3。'},{id:'new',role:'user',content:'更正需求为4。'}],sources=sourceCatalog(messages);
  for(const refs of [[sources[0].id,sources[1].id],[sources[1].id,sources[0].id]]){
    const c={format:'llm4orovo.submission.v3',modelPurpose:'final_task',facts:[fact('old',sources[0].id),fact('new',sources[1].id,{sourceRefs:refs,supersedes:['old']})],bindings:[binding('new',['method:conditions'],'not_applicable')],gaps:[],budget:null};assert.equal(validateContract(c,messages).facts[0].status,'superseded');
  }
});
test('fresh semantic review can reuse unchanged solver mathematics after an explicit update',async()=>{
  const h=harness();await h.send(prompt);const final=await h.send('确认仍然没有额外费用，其他条件不变。');assert.equal(final.stage,'complete');assert.equal(final.resultContract.evidenceReused,true);assert.equal(h.calls(),4);assert.equal(h.solves(),1);
});
test('reuse rejects stored values or objective that no longer pass numerical validation',async()=>{
  const h=harness();await h.send(prompt);h.records.get('r1').objective=999;const final=await h.send('确认原条件未变。');assert.equal(final.stage,'complete');assert.equal(h.solves(),2);assert.notEqual(final.resultContract.evidenceReused,true);
});
test('infeasible base conditions are not falsely attributed to insufficient budget',()=>{
  const text=resultText({budgetDecision:'all_infeasible',solverStatus:'infeasible',semanticReviewStatus:'no_issue_found'});assert.doesNotMatch(text,/预算不足/);assert.match(text,/预算限制/);
});
test('outdated question metadata remains invalid despite flexible answer wording',async()=>{
  const h=harness({budget:true}),flow=await h.send(prompt);const q=flow.questions[0];assert.throws(()=>validateReply(flow.task,{...to(q),factVersion:q.factVersion-1}));
});
test('explicit budget corrections outside the old interval are rebuilt and reviewed, not locked out',async()=>{
  assert.equal(resolveBudgetReply({budget:{lower:5,upper:7,unit:'USD'}},'更正预算为8美元').status,'revision');
  const h=harness({planner:({conf,context})=>{if(conf.tool.name==='review_optimization')return reviewed(context.contract);const ms=context.originalMessages,c=ledger(ms,true);if(ms.length>1){const source=sourceCatalog(ms).find(s=>s.messageId===ms.at(-1).id).id;c.facts.push(fact('b-new',source,{unit:'USD',value:8,supersedes:['b']}));c.bindings[1]=binding('b-new',['gap:gb-new'],'deferred_to_budget_gate');c.gaps=[{id:'gb-new',factId:'b-new',kind:'budget'}];Object.assign(c.budget,{factId:'b-new',gapId:'gb-new',lower:8,upper:8});}return submit(c);}});
  await h.send(prompt);const final=await h.send('更正预算为8美元');assert.equal(final.stage,'complete');assert.equal(final.resultContract.budgetDecision,'all_feasible');assert.equal(final.resultContract.evidenceReused,true);assert.equal(h.calls(),4);assert.equal(h.solves(),1);
});
test('an ambiguous range answer retains the interval conflict and current question',async()=>{
  const h=harness({budget:true});await h.send(prompt);const out=await h.send('8美元');assert.equal(out.decision.code,'budget_conflict');assert.equal(out.questions.length,1);assert.equal(h.calls(),2);const fixed=await h.send('5.5美元',to(out.questions[0]));assert.equal(fixed.resultContract.budgetDecision,'all_infeasible');assert.equal(h.calls(),2);
});
test('edits to a rejected answer cannot be excluded from context by stale exclusion metadata',async()=>{
  const h=harness({budget:true});await h.send(prompt);await h.send('预算为5元');h.conversation.messages.find(m=>m.content==='预算为5元').content='预算为5元，需求也改成10';await h.send('5美元');assert.equal(h.calls(),4); // Fresh modeling + review are required.
});
test('missing or same-age replacement evidence still cannot erase an unresolved gap',async()=>{
  const messages=[{id:'root',role:'user',content:'需要补充a和b。'}],c=missing(messages,[]),source=sourceCatalog(messages)[0].id;c.facts.push(fact('fake',source,{supersedes:['a']}));assert.throws(()=>validateContract(c,messages),/INVALID_SUPERSESSION/);
});
test('cached budget values are numerically checked again before a local answer is delivered',async()=>{
  const h=harness({budget:true});await h.send(prompt);h.records.get('r1').values.x=0;await h.send('5美元');assert.equal(h.calls(),4);assert.equal(h.solves(),2);
});
test('a pending budget cannot skip review of a reply that also changes another condition',async()=>{
  const h=harness({budget:true});await h.send(prompt);await h.send('预算为5美元，需求改为10');assert.equal(h.calls(),4);
});
test('unchanged requests after completion still stop without spending additional calls',async()=>{
  const h=harness();await h.send(prompt);const stopped=await h.send(prompt);assert.equal(stopped.decision.code,'no_new_information');assert.equal(h.calls(),2);assert.equal(h.solves(),1);
});
test('resending a completed budget answer does not lose duplicate protection when its question closes',async()=>{
  const h=harness({budget:true});await h.send(prompt);await h.send('5美元');const stopped=await h.send('5美元');assert.equal(stopped.decision.code,'no_new_information');assert.equal(h.calls(),2);assert.equal(h.solves(),1);
});
