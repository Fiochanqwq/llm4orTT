import fs from 'node:fs';
import { controllerReply } from '../baselines/0.7.3-research-20261013/server/experiments.mjs';
import { resultText } from '../baselines/0.7.3-research-20261013/shared/result-contract.mjs';
const card={hidden_fixed_budget:340,unit:'USD',oracle_reply:'已批准且固定的预算为 340 美元，不能追加。'};
const cases=[
  {name:'natural language actual budget',flow:{stage:'clarification',questions:[{question:'请告诉我实际批准了多少钱？'}],task:{}},expected:'340 USD'},
  {name:'multiple questions',flow:{stage:'clarification',questions:[{field:'budget',question:'实际预算是多少？'},{field:'budget',question:'能否追加预算？'}],task:{}},expected:'fixed amount and no additions'},
  {name:'additional budget willingness must not disclose amount',flow:{stage:'clarification',questions:[{field:'budget',question:'是否愿意追加预算？'}],task:{}},expected:'fixed; no amount disclosure'},
  {name:'unit included',flow:{stage:'clarification',questions:[{field:'budget',question:'What is the approved budget?'}],task:{}},expected:'340 USD'}
];
const results=cases.map(c=>({name:c.name,expected:c.expected,actual:controllerReply(c.flow,card)}));
results.push({name:'B4 exact amount wording',expected:'actual budget 340 USD, not the original interval',actual:resultText({budgetDecision:'all_feasible',budgetAnswer:{status:'amount',value:340},budget:{lower:320,upper:340,unit:'USD'},solverStatus:'optimal'})});
const report={version:'0.7.3',purpose:'pre-change reproduction; no provider calls',results};
fs.writeFileSync('qa/v074-before.json',JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
