import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { SolverService } from '../server/solver.mjs';
import { resultContract } from '../shared/result-contract.mjs';
import { budgetDecision } from '../server/budget-relevance.mjs';
const directory=path.resolve('qa','v07-examples-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(directory,{recursive:true});
const solver=new SolverService(directory),cards=JSON.parse(fs.readFileSync('experiments/budget-boundary-20261011/answers.private.json','utf8')),rows=[];
const families={
  '703345038':{cost:[100,80],constraints:[[10,7,30],[8,15,50]]},
  '-964250787':{cost:[2,3],constraints:[[1.5,5,5],[3,1,8]]}
};
try{for(const card of cards){
  const family=families[card.source_id]||{cost:[300,200],constraints:[[2,4,10],[2,1,9],[4,2,15]]};
  const hydrogen=card.question_id==='NL4OPT-NATIVE-HYDROGEN';
  const model={format:'llm4orovo.lp.v1',name:'offline_control',sense:'minimize',variables:['x','y'].map(name=>({name,type:hydrogen?'integer':'continuous',lower:0,upper:null})),objective:hydrogen?{x:1,y:1}:{x:family.cost[0],y:family.cost[1]},constraints:hydrogen?[{name:'transport',terms:{x:50,y:30},sense:'>=',rhs:1000},{name:'budget',terms:{x:500,y:200},sense:'<=',rhs:3750},{name:'strict_order',terms:{x:1,y:-1},sense:'<=',rhs:-1}]:family.constraints.map(([x,y,rhs],i)=>({name:'requirement_'+i,terms:{x,y},sense:'>=',rhs}))};
  const r=solver.start({model,engine:'highs',seconds:30,problem:'Offline mathematical control '+card.question_id});while(r.status==='running')await new Promise(resolve=>setTimeout(resolve,50));
  const delivery=resultContract(r);let budget=null,decision=null;
  if(!hydrogen){budget=card.hidden_fixed_budget; if(budget===null){const prompt=JSON.parse(fs.readFileSync('experiments/budget-boundary-20261011/questions.public.json','utf8')).find(q=>q.question_id===card.question_id).prompt;budget=Number(prompt.match(/总预算为 (\d+(?:\.\d+)?)/)?.[1]);}if(!Number.isFinite(budget))throw Error('Missing control budget');decision=budgetDecision(r,{lower:budget,upper:budget});}
  const observed=hydrogen?r.status:decision.status==='all_infeasible'?'infeasible':decision.status==='all_feasible'?'optimal':'uncertain';assert.equal(observed,card.expected_final_status,card.question_id);
  if(r.status==='optimal'){assert.equal(delivery.displayValidation.feasible,true);const [n,d='1']=card.minimum_cost_exact.split('/');assert.ok(Math.abs(r.objective-Number(n)/Number(d))<1e-6);}
  rows.push({caseId:card.question_id,baseId:card.source_id,runId:r.id,expected:card.expected_final_status,observed,objective:r.objective??null,displayValidation:delivery.displayValidation,budgetDecision:decision});
}
fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify({kind:'offline_math_controls',providerCalls:0,controls:rows.length,independentBaseProblems:4,notModelPerformanceEvidence:true,rows},null,2));console.log(JSON.stringify({directory,passed:rows.length,providerCalls:0}));
}finally{solver.close();}
