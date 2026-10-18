// Frozen synthetic fault injection, not sampled LLM behavior. No private labels
// enter execution; the runner gets only scripted candidate/repaired responses.
import { validateModel } from '../../shared/solver-model.mjs';
const variable=(name,type='continuous',upper=null)=>({name,type,lower:0,upper});
const row=(name,terms,sense,rhs)=>({name,terms,sense,rhs});
const model=(sense,objective,constraints,variables=[variable('x'),variable('y')])=>validateModel({format:'llm4orovo.lp.v1',name:'Synthetic controlled task',sense,variables,objective,constraints});
export function buildEvidenceCases(){
  const cases=[];
  function add(group,family,variant,prompt,correct,mutate=null){
    const candidate=structuredClone(correct);mutate?.(candidate);
    cases.push({id:`${group}-${family}-${variant}`,baseId:`${group}-${family}`,group,family,prompt,expectedDecision:group==='A'?'repair':group==='B'?'clarify':'deliver',correctModel:correct,candidateModel:candidate});
  }
  for(const k of [0,1]){
    const cap=8+k, demand=5+k;
    add('A','omission',k,`最大化收益 7x+4y。数量均为非负连续量。机器限制 2x+y<=${cap}，人工限制 x+3y<=${cap+4}，订单上限 x<=2。`,model('maximize',{x:7,y:4},[row('machine',{x:2,y:1},'<=',cap),row('labor',{x:1,y:3},'<=',cap+4),row('orders',{x:1},'<=',2)]),m=>{m.constraints.pop();m.constraints[0].rhs=cap+1;});
    add('A','integer',k,`最大化收益 7x+4y。所有变量均为非负整数。资源限制 2x+3y<=${7+2*k}。`,model('maximize',{x:7,y:4},[row('capacity',{x:2,y:3},'<=',7+2*k)],[variable('x','integer'),variable('y','integer')]),m=>m.variables.forEach(v=>v.type='continuous'));
    add('A','sense',k,`最小化成本 3x+5y。数量均为非负连续量。需求 x+y>=${demand}，产能 x<=${cap}，y<=${cap+1}。`,model('minimize',{x:3,y:5},[row('demand',{x:1,y:1},'>=',demand),row('xcap',{x:1},'<=',cap),row('ycap',{y:1},'<=',cap+1)]),m=>m.sense='maximize');
    add('A','units',k,`最大化收益 7x+4y。数量均为非负连续量。每件 x 消耗 200 千克，每件 y 消耗 300 千克；总原料 ${2+k} 吨。模型统一以千克计。`,model('maximize',{x:7,y:4},[row('material',{x:200,y:300},'<=',(2+k)*1000)]),m=>m.constraints[0].rhs=2+k);
    add('B','unbounded',k,`最大化收益 ${3+k}x。x 为非负连续量，尚未说明可用产能上限。`,model('maximize',{x:3+k},[],[variable('x')]));
    add('B','coupled_ray',k,`最大化收益 ${5+k}x+3y。数量均为非负连续量。配比 x-y<=2，总量 x+y>=4，未说明总工时上限。`,model('maximize',{x:5+k,y:3},[row('ratio',{x:1,y:-1},'<=',2),row('minimum',{x:1,y:1},'>=',4)]));
    add('B','conflict',k,`最小化成本 4x+5y。数量均为非负连续量。资源 2x+y<=${12+3*k}，x+2y<=${12+3*k}；订单 x+y>=${9+2*k}。请检查订单与资源是否冲突。`,model('minimize',{x:4,y:5},[row('resource_a',{x:2,y:1},'<=',12+3*k),row('resource_b',{x:1,y:2},'<=',12+3*k),row('order',{x:1,y:1},'>=',9+2*k)]));
    add('B','zero_missing_demand',k,`最小化处理成本 ${2+k}x+y。数量均为非负连续量。容量 x+y<=${cap}。业务要求完成处理任务，但最低处理量未说明。`,model('minimize',{x:2+k,y:1},[row('capacity',{x:1,y:1},'<=',cap)]));
    add('C','production',k,`最大化收益 7x+4y。数量均为非负连续量。机器 2x+y<=${cap}，人工 x+3y<=${cap+4}。`,model('maximize',{x:7,y:4},[row('machine',{x:2,y:1},'<=',cap),row('labor',{x:1,y:3},'<=',cap+4)]));
    add('C','covering',k,`最小化成本 3x+5y。数量均为非负连续量。需求 x+y>=${demand}，能力 x<=${cap}，y<=${cap+1}。`,model('minimize',{x:3,y:5},[row('demand',{x:1,y:1},'>=',demand),row('xcap',{x:1},'<=',cap),row('ycap',{y:1},'<=',cap+1)]));
    add('C','equality',k,`最小化成本 2x+3y。数量均为非负连续量。总量 x+y=${demand}，限制 x<=3。`,model('minimize',{x:2,y:3},[row('balance',{x:1,y:1},'=',demand),row('xcap',{x:1},'<=',3)]));
    add('C','binary',k,`最大化收益 ${5+k}x+3y。所有变量均为二元，取值为 0 或 1。资源 2x+3y<=4。`,model('maximize',{x:5+k,y:3},[row('resource',{x:2,y:3},'<=',4)],[variable('x','binary',1),variable('y','binary',1)]));
  }
  return cases;
}

// Independent small-instance oracle: enumerate integer points or all 2D
// vertices. No HiGHS/Pyomo and no candidate solution used as ground truth.
export function referenceOptimum(m){
  if(m.variables.length!==2)throw Error('Oracle supports exactly two variables');
  const [x,y]=m.variables.map(v=>v.name),lines=m.constraints.map(c=>[c.terms[x]||0,c.terms[y]||0,c.rhs]);
  for(const [i,v] of m.variables.entries())for(const bound of [v.lower,v.upper])if(bound!==null)lines.push([i===0?1:0,i===1?1:0,bound]);
  let points=[];
  if(m.variables.every(v=>v.type!=='continuous')){for(let a=0;a<=100;a++)for(let b=0;b<=100;b++)points.push([a,b]);}
  else for(let i=0;i<lines.length;i++)for(let j=0;j<i;j++){
    const [a,b,c]=lines[i],[d,e,f]=lines[j],det=a*e-b*d;if(Math.abs(det)>1e-10)points.push([(c*e-b*f)/det,(a*f-c*d)/det]);
  }
  const valid=points.filter(p=>m.variables.every((v,i)=>(v.lower===null||p[i]>=v.lower-1e-7)&&(v.upper===null||p[i]<=v.upper+1e-7))&&m.constraints.every(c=>{const z=(c.terms[x]||0)*p[0]+(c.terms[y]||0)*p[1]-c.rhs;return c.sense==='='?Math.abs(z)<1e-7:c.sense==='<='?z<1e-7:z>-1e-7;}));
  if(!valid.length)throw Error('No oracle optimum');
  valid.sort((a,b)=>(m.sense==='maximize'?-1:1)*((m.objective[x]||0)*(a[0]-b[0])+(m.objective[y]||0)*(a[1]-b[1])));
  return {values:{[x]:valid[0][0],[y]:valid[0][1]},objective:(m.objective[x]||0)*valid[0][0]+(m.objective[y]||0)*valid[0][1]};
}
