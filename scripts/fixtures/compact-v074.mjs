import { compactVersion, compactReviewVersion } from '../../shared/compact-protocol.mjs';
export const fertilizerModel={format:'llm4orovo.lp.v1',name:'Fertilizer fixture',sense:'minimize',variables:[{name:'C',type:'continuous',lower:0,upper:null},{name:'Y',type:'continuous',lower:0,upper:null}],objective:{C:2,Y:3},constraints:[{name:'nitrogen',terms:{C:1.5,Y:5},sense:'>=',rhs:5},{name:'vitamins',terms:{C:3,Y:1},sense:'>=',rhs:8}]};
export function compactPlan(input,{model=fertilizerModel,budget=true,badSource=false,entities=false}={}){
  const data=typeof input==='string'?JSON.parse(input):input,refs=data.sourceCatalog.slice(0,16).map(s=>s.id);
  const contract={format:compactVersion,requirements:[{statement:'Original objective, domains and constraints',sources:badSource?['s99999']:refs,targets:[...model.variables.map(v=>({kind:'variable',name:v.name})),{kind:'objective'},...model.constraints.map(c=>({kind:'constraint',name:c.name}))]}],missing:[],budget:budget?{lower:5,upper:6,unit:'USD',sources:refs,confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true}:null};
  return {calls:[{name:'submit_optimization',arguments:{action:'solve',model_json:JSON.stringify(model),contract_json:JSON.stringify(contract),message:'已依据公开题面建立模型。',questions:[],...(entities?{entities:[{variable:'C',label:'肥料 C',unit:'千克',sources:refs},{variable:'Y',label:'肥料 Y',unit:'千克',sources:refs}]}:{})}}],usage:{input:30,output:40}};
}
export function compactReviewed({budget=true,status='no_issue_found',diagnostics=[],checks={}}={}){
  return {calls:[{name:'review_optimization',arguments:{review_json:JSON.stringify({format:compactReviewVersion,status,checks:{requirements:'checked',mathematics:'checked',amendments:'checked',budget:budget?'checked':'not_applicable',...checks},diagnostics,budgetApplicability:budget?'supported':'not_applicable'})}}],usage:{input:20,output:10}};
}
