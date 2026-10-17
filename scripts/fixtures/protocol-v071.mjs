import { targetCatalog } from '../../shared/protocol-schema.mjs';
export const model={format:'llm4orovo.lp.v1',name:'Protocol_QA',sense:'minimize',variables:['C','Y'].map(name=>({name,type:'continuous',lower:0,upper:null})),objective:{C:2,Y:3},constraints:[{name:'nitrogen',terms:{C:1.5,Y:5},sense:'>=',rhs:5},{name:'vitamins',terms:{C:3,Y:1},sense:'>=',rhs:8}]};
export function fixtureResponse(config,messages,scenario='valid') {
  const envelope=JSON.parse(messages[0].content),input=envelope.context||envelope,sources=input.sourceCatalog;
  const base=scenario==='valid';
  const c={format:'llm4orovo.submission.v3',modelPurpose:base?'budget_threshold_base':'final_task',facts:[{id:'facts',kind:'specified_requirements',sourceRefs:[sources[0].id],unit:'USD',value:null,supersedes:[]}],bindings:[{factIds:['facts'],targetRefs:targetCatalog(model).filter(t=>t.required).map(t=>t.id),disposition:'encoded',reason:''}],gaps:[],budget:null};
  if(base){c.facts.push({id:'budget',kind:'fixed_budget',sourceRefs:[sources.at(-1).id],unit:'USD',value:{lower:5,upper:6},supersedes:[]});c.gaps.push({id:'gap',factId:'budget',kind:'budget'});c.bindings.push({factIds:['budget'],targetRefs:['gap:gap'],disposition:'deferred_to_budget_gate',reason:''});c.budget={factId:'budget',gapId:'gap',lower:5,upper:6,unit:'USD',costTerms:model.objective,confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true};}
  let args;
  if(config.tool.name==='review_optimization'){
    const review={format:'llm4orovo.review.v3',status:scenario==='uncertain'?'uncertain':'no_issue_found',diagnostics:scenario==='uncertain'?[{code:'qa_uncertainty',factIds:['facts'],targetIds:['variable:C'],gapIds:[],sourceRefs:[sources[0].id],evidence:'Software fixture: unresolved semantic uncertainty.',repairable:false}]:[],factIds:c.facts.map(f=>f.id),targetIds:targetCatalog(model).filter(t=>t.required).map(t=>t.id),gapIds:c.gaps.map(g=>g.id),budgetApplicability:base?'supported':'not_applicable'};
    if(base&&!envelope.issue)review.targetIds.push('objective:total_cost'); // One realistic recorded failure type.
    args={review_json:JSON.stringify(review)};
  }else{if(scenario==='bad-source')c.facts[0].sourceRefs=['source:nonexistent'];args={action:'solve',model_json:JSON.stringify(model),contract_json:JSON.stringify(c),message:'QA injected provider fixture',questions:[]};}
  return {calls:[],text:JSON.stringify(args),truncated:false,usage:{input:10,output:20}};
}
