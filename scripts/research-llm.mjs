// Bounded model calls using existing credentials in memory; never copy credentials.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import OpenAI from 'openai';
import { fileURLToPath } from 'node:url';
import { Store } from '../server/store.mjs';
import { vault } from '../server/secrets.mjs';
import { readableError } from '../server/providers.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'outputs/inverse/pilot-20261019-v3');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const write=(p,v)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,JSON.stringify(v,null,2));};
const protocol=read(path.join(out,'protocol.json'));
const state=read(path.join(process.env.LOCALAPPDATA,'FYPPPPP/workspace/inverse-workspace.json'));
const config=await Store.prototype.credentials.call({data:state,vault},state.preferences.provider);
config.maxTokens=protocol.max_output_tokens;
if(config.id!=='deepseek')throw Error('Frozen v3 protocol requires the configured DeepSeek provider');
const client=new OpenAI({apiKey:config.apiKey,baseURL:config.baseURL,maxRetries:0,timeout:protocol.model_timeout_ms});
const mode=process.argv[2];
const bank=read(path.join(out,'public/feature-bank.json'));
const responsePath=path.join(out,`llm/${mode}.json`);
const records=fs.existsSync(responsePath)?read(responsePath):{};
const budgetPath=path.join(out,'llm/call-budget.json');
let budget=fs.existsSync(budgetPath)?read(budgetPath):{attempts:0};
let requests;
if(mode==='logs') requests=read(path.join(out,'generator/log-requests.json'));
else if(mode==='proposals') requests=Object.entries(read(path.join(out,'llm/logs.json'))).filter(([,v])=>v.status==='ok').map(([id,v])=>({id,logs:v.value,bank}));
else if(mode==='guesses') requests=read(path.join(out,'public/guess-requests.json')).filter(r=>r.logs?.status==='ok').map(r=>({...r,logs:r.logs.value}));
else if(mode==='feedback') requests=read(path.join(out,'public/feedback-requests.json'));
else throw Error('mode must be logs/proposals/guesses/feedback');

function prompt(r){
 const common='这是有限候选排班研究。每次从六个方案中选一个，使已知工资加隐性代价最小。权重非负且在[0,10]。特征定义对所有场景共用。不得访问外部资料或执行代码。只输出一个JSON对象。';
 if(mode==='logs') return '把下列业务事实写成三至五条自然的中文运营日志，像员工抱怨和临时备注。保留所有业务含义，不直接写字段ID，不捏造成本数字、权重大小或排序。夜班若出现，说明超过一次才有额外负担。无关闲聊也保留。返回 {"logs":["日志"]}。\n'+JSON.stringify(r);
 if(mode==='proposals'||mode==='feedback') return common+'\n根据日志'+(mode==='feedback'?'以及历史决策和当前模型的次优性残差补充遗漏的特征；只依据提供的信息，不保证残差必须下降':'选择可能影响决策的特征')+'。从bank中选择，逐项保留id/kind/threshold。不要估计权重。返回 {"hypotheses":[{"id":"handover","kind":"linear"}],"explanation":"简短依据"}。没有依据可返回空列表。\n'+JSON.stringify(r);
 return common+'\n只用日志和历史选择，直接推测全部六项权重；不调用求解器。chosen为从零开始的方案下标。无关特征可以为零。返回 {"theta":{"night":0,"handover":0,"travel":0,"overtime":0,"color":0,"badge":0}}，用你的估计替换数值。\n'+JSON.stringify(r);
}
let cursor=0;
async function worker(){
 while(cursor<requests.length){
  const r=requests[cursor++];
  if(records[r.id])continue;
  if(budget.attempts>=protocol.max_model_calls)throw Error('Frozen model call budget exhausted');
  budget.attempts++;write(budgetPath,budget);
  const content=prompt(r), started=new Date().toISOString();
  const raw={id:r.id,mode,started,provider:config.id,model:config.model,maxOutputTokens:config.maxTokens,
   thinking:protocol.thinking,temperature:protocol.temperature,responseFormat:protocol.response_format,
   prompt:content,promptSha256:crypto.createHash('sha256').update(content).digest('hex'),text:'',usage:{}};
  try{
   const response=await client.chat.completions.create({model:config.model,messages:[{role:'system',content:'You are an optimization research assistant. Return only the requested JSON object. Do not claim to have run tools.'},{role:'user',content}],
    max_tokens:config.maxTokens,thinking:{type:protocol.thinking},temperature:protocol.temperature,
    response_format:{type:protocol.response_format},stream:false},{signal:AbortSignal.timeout(protocol.model_timeout_ms)});
   raw.text=response.choices[0]?.message?.content||'';
   raw.usage={input:response.usage?.prompt_tokens??null,output:response.usage?.completion_tokens??null};
   raw.metadata={responseId:response.id,returnedModel:response.model,finishReason:response.choices[0]?.finish_reason};
   if(raw.metadata.finishReason!=='stop')throw Error('Incomplete model response');
   const clean=raw.text.trim().replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,'');
   const value=JSON.parse(clean);
   if(mode==='logs'&&(!Array.isArray(value.logs)||!value.logs.length||value.logs.some(v=>typeof v!=='string')))throw Error('Invalid logs schema');
   if(mode==='logs'&&value.logs.some(v=>/\d/.test(v)))throw Error('Numeric log rejected by leakage guard');
   records[r.id]={status:'ok',value};raw.status='ok';
  }catch(error){raw.status='failed';raw.error=error instanceof SyntaxError?'Invalid JSON':readableError(error);records[r.id]={status:'failed',error:raw.error};}
  raw.finished=new Date().toISOString();
  write(path.join(out,`llm/raw/${mode}-${r.id}.json`),raw);write(responsePath,records);
  console.log(`${mode}: ${Object.keys(records).length}/${requests.length}; ${r.id}: ${raw.status}`);
 }
}
await Promise.all(Array.from({length:protocol.concurrency},()=>worker()));
write(responsePath,records);
