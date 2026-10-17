import test from 'node:test';
import assert from 'node:assert/strict';
import {generate,planOptimization} from '../server/providers.mjs';
import {parseSolverResponse} from '../server/solver-response.mjs';
import {analysisRow} from '../server/exports.mjs';
import {ExperimentService} from '../server/experiments.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const config={id:'deepseek',apiKey:'fake-key',baseURL:'https://api.deepseek.com',model:'deepseek-flash',language:'zh-CN',maxTokens:1000};
const messages=[{role:'user',content:'offline'}];
const response=events=>new Response(events.map(e=>'data: '+(typeof e==='string'?e:JSON.stringify(e))+'\n\n').join(''),{headers:{'content-type':'text/event-stream'}});
test('DeepSeek requests explicit documented defaults and preserves final usage and response identity',async()=>{
 let body;const chunks=[];for await(const c of generate(config,messages,new AbortController().signal,{fetch:async(_url,init)=>{
  body=JSON.parse(init.body);return response([{id:'reply',model:'deepseek-flash',choices:[{delta:{reasoning_content:'not an answer'}}]},{id:'reply',model:'deepseek-flash',choices:[{delta:{content:'answer'},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:20,prompt_cache_hit_tokens:5,completion_tokens_details:{reasoning_tokens:12}}},'[DONE]']);
 }}))chunks.push(c);
 assert.equal(body.thinking.type,'enabled');assert.equal(body.reasoning_effort,'high');assert.equal(body.stream_options.include_usage,true);
 assert.equal(chunks.map(c=>c.text||'').join(''),'answer');assert.equal(chunks.find(c=>c.rawUsage).rawUsage.prompt_cache_hit_tokens,5);
 assert.equal(chunks.at(-1).requestMetadata.responseId,'reply');
});
test('DeepSeek truncated transport is not a completed answer',async()=>{
 await assert.rejects(async()=>{for await(const _ of generate(config,messages,new AbortController().signal,{fetch:async()=>response([{choices:[{delta:{content:'partial'}}]},'[DONE]'])})){}},/without completion/);
});
test('DeepSeek tool stream assembles fragments and records transport metadata without reasoning',async()=>{
 const result=await planOptimization(config,messages,new AbortController().signal,{fetch:async()=>response([
 {id:'tool',model:'deepseek-flash',choices:[{delta:{tool_calls:[{index:0,id:'call',function:{name:'submit_optimization',arguments:'{"action":'}}]}}]},
 {choices:[{delta:{tool_calls:[{index:0,function:{arguments:'"clarify"}'}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:4,completion_tokens:5}},'[DONE]'])});
 assert.deepEqual(JSON.parse(result.calls[0].arguments),{action:'clarify'});assert.equal(result.truncated,false);assert.equal(result.requestMetadata.finishReason,'tool_calls');
});
test('worker result cannot overwrite run identity or claim an optimal result without values',()=>{
 const model={variables:[{name:'x'}]};
 const result=parseSolverResponse(JSON.stringify({id:'overwrite',model:{},status:'optimal',objective:3,values:{x:3}}),model);
 assert.equal(result.id,undefined);assert.equal(result.model,undefined);assert.equal(result.values.x,3);
 for(const value of [{status:'running'},{status:'optimal',objective:3,values:{}},{status:'optimal',objective:3,values:{x:'3'}}])assert.throws(()=>parseSolverResponse(JSON.stringify(value),model));
});
test('experiment report retains public question, answer, unknown usage and provider metadata',()=>{
 const row=analysisRow({id:'run',publicPrompt:'question',conversation:{messages:[{role:'assistant',content:'answer'}]},events:[{id:'r',state:'completed',response:{usage:{input:null,output:2},requestMetadata:{responseId:'reply'},rawUsage:{completion_tokens:2}}}]});
 assert.equal(row.publicPrompt,'question');assert.equal(row.answer,'answer');assert.equal(row.unknownUsageRequests,1);assert.equal(row.requests[0].requestMetadata.responseId,'reply');
});
test('batch marks truncated generation partial and preserves raw usage, without invoking a solver',async()=>{
 const dir=path.resolve('qa','deepseek-offline-'+crypto.randomUUID());fs.mkdirSync(dir,{recursive:true});
 const service=new ExperimentService(dir,{store:{credentials:async()=>config},solver:{start(){assert.fail('must not invoke solver');}},generator:async function*(){yield {text:'partial'};yield {usage:{input:1,output:2},rawUsage:{prompt_tokens:1,completion_tokens:2}};yield {warning:'output limit'};}});
 const batch=await service.create({provider:'deepseek',cases:[{id:'x',prompt:'offline'}],presets:['native_api'],requestCap:4});service.action(batch.id,'start');
 while(service.working)await new Promise(r=>setTimeout(r,5));const run=service.run(batch.runs[0].id);
 assert.equal(run.status,'partial');assert.equal(run.failure.code,'OUTPUT_TRUNCATED');assert.equal(run.events.find(e=>e.state==='completed').response.rawUsage.completion_tokens,2);
});
