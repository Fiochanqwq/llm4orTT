import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import net from 'node:net';
import { Store } from '../server/store.mjs';
import { ExperimentService } from '../server/experiments.mjs';
import { SolverService } from '../server/solver.mjs';
import { startServer } from '../server/http.mjs';
import { createModelQueue } from '../server/model-queue.mjs';
import { queuedSolve } from '../server/solver-queue.mjs';
import { demoModel } from '../shared/solver-model.mjs';
const directory=()=>{const dir=path.resolve('qa','resilience-'+crypto.randomUUID());fs.mkdirSync(dir,{recursive:true});return dir;};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const fault=()=>Object.assign(new Error('injected write failure'),{code:'ENOSPC'});

test('workspace recovers invalid structures without copying them over a good backup',()=>{
  const dir=directory(),store=new Store(dir,{});store.create();store.save();
  const backup=fs.readFileSync(store.backup,'utf8');
  for(const conversations of [[null],[{id:'bad',title:'bad',messages:[null]}]]){
    fs.writeFileSync(store.file,JSON.stringify({version:1,preferences:{},providers:{},conversations}));
    const recovered=new Store(dir,{});
    assert.equal(recovered.data.conversations.length,1);assert.equal(recovered.recovery.restoredFromBackup,true);
    assert.deepEqual(JSON.parse(fs.readFileSync(recovered.recovery.corrupted,'utf8')).conversations,conversations);
  }
  assert.equal(JSON.parse(backup).conversations.length,1);
});
test('failed quarantine leaves the original and good backup untouched',()=>{
  const store=new Store(directory(),{});store.create();store.save();
  fs.writeFileSync(store.file,'{broken');const before=fs.readFileSync(store.backup,'utf8'),rename=fs.renameSync;
  fs.renameSync=function(from,to){if(String(to).includes('.corrupt-'))throw fault();return rename(from,to);};
  try{assert.throws(()=>new Store(store.directory,{}),{code:'STORAGE_UNAVAILABLE'});}finally{fs.renameSync=rename;}
  assert.equal(fs.readFileSync(store.file,'utf8'),'{broken');assert.equal(fs.readFileSync(store.backup,'utf8'),before);
});
test('missing primary restores backup and successful saves advance the recovery point',()=>{
  const store=new Store(directory(),{});store.create();store.create();store.create();
  assert.equal(JSON.parse(fs.readFileSync(store.backup,'utf8')).conversations.length,2);
  fs.unlinkSync(store.file);const recovered=new Store(store.directory,{});
  assert.equal(recovered.data.conversations.length,2);assert.equal(recovered.recovery.restoredFromBackup,true);
});
test('when both copies are damaged, both originals survive empty-workspace recovery',()=>{
  const dir=directory(),file=path.join(dir,'workspace.json');fs.writeFileSync(file,'{primary broken');fs.writeFileSync(file+'.bak','{backup broken');
  const recovered=new Store(dir,{});assert.equal(recovered.data.conversations.length,0);assert.equal(recovered.recovery.restoredFromBackup,false);
  assert.equal(fs.readFileSync(recovered.recovery.corrupted,'utf8'),'{primary broken');assert.equal(fs.readFileSync(recovered.recovery.backupCorrupted,'utf8'),'{backup broken');
});
test('workspace save failure rolls back existing references and new records, blocks further writes',()=>{
  const store=new Store(directory(),{}),conversation=store.create(),write=fs.writeFileSync;
  const before=structuredClone(store.data),disk=fs.readFileSync(store.file,'utf8');
  fs.writeFileSync=()=>{throw fault();};
  try{conversation.title='unsaved';assert.throws(()=>store.create(),{code:'STORAGE_UNAVAILABLE'});}finally{fs.writeFileSync=write;}
  assert.deepEqual(store.data,before);assert.equal(store.get(conversation.id),conversation);assert.equal(conversation.title,before.conversations[0].title);
  assert.equal(fs.readFileSync(store.file,'utf8'),disk);assert.throws(()=>store.create(),{code:'STORAGE_UNAVAILABLE'});
});
test('primary rename failure rolls back and removes temporary files',()=>{
  const store=new Store(directory(),{}),rename=fs.renameSync,before=structuredClone(store.data);
  fs.renameSync=function(from,to){if(to===store.file)throw fault();return rename(from,to);};
  try{assert.throws(()=>store.create(),{code:'STORAGE_UNAVAILABLE'});}finally{fs.renameSync=rename;}
  assert.deepEqual(store.data,before);assert.equal(fs.readdirSync(store.directory).some(f=>f.endsWith('.tmp')),false);
});
test('corrupt experiment batch and run files are isolated while healthy history remains available',async()=>{
  const dir=directory(),service=new ExperimentService(dir,{runner:async()=>({status:'complete'})});
  const batch=await service.create({cases:[{id:'a',prompt:'offline'}],presets:['full']});
  const file=path.join(service.directory,crypto.randomUUID()+'.json');fs.writeFileSync(file,'{broken');
  const runId=batch.runs[0].id;fs.mkdirSync(path.dirname(service.runPath(runId)),{recursive:true});fs.writeFileSync(service.runPath(runId),'{broken');
  const next=new ExperimentService(dir,{runner:async()=>({status:'complete'})});
  assert.equal(next.list().length,1);assert.equal(next.skipped.length,1);assert.equal(next.run(runId),null);assert.equal(next.skipped.length,2);assert.equal(fs.readFileSync(file,'utf8'),'{broken');
});
test('background persistence failure pauses experiments without unhandled rejection or another dispatch',async()=>{
  const dir=directory();let release,entered;const ready=new Promise(r=>entered=r),gate=new Promise(r=>release=r);let calls=0;
  const service=new ExperimentService(dir,{runner:async()=>{calls++;entered();await gate;return {status:'complete'};}});
  const batch=await service.create({cases:[{id:'a',prompt:'offline'},{id:'b',prompt:'offline'}],presets:['full']});
  service.action(batch.id,'start');await ready;
  const write=fs.writeFileSync;fs.writeFileSync=function(file,...args){if(String(file).includes(path.join('experiments','runs')))throw fault();return write(file,...args);};
  try{release();await service.close();}finally{fs.writeFileSync=write;}
  assert.equal(calls,1);assert.equal(service.view(batch.id).status,'paused');assert.equal(service.working,false);
  assert.equal(service.storageError.code,'STORAGE_UNAVAILABLE');assert.throws(()=>service.action(batch.id,'resume'),{code:'STORAGE_UNAVAILABLE'});
});
test('solver completion persistence failures remain visible and block further solver work',()=>{
  const service=new SolverService(directory()),record={id:crypto.randomUUID(),status:'stopped'},write=fs.writeFileSync;
  fs.writeFileSync=()=>{throw fault();};try{assert.doesNotThrow(()=>service.saveCompletion(record));}finally{fs.writeFileSync=write;}
  assert.ok(record.persistenceError);assert.ok(service.info().storageError);assert.throws(()=>service.start({}),{code:'STORAGE_UNAVAILABLE'});
});
test('real solver completion survives a failed result write and retains its in-memory result',async()=>{
  const service=new SolverService(directory());
  const record=service.start({engine:'highs',seconds:2,model:demoModel}),write=fs.writeFileSync;
  assert.equal(record.status,'running');
  fs.writeFileSync=function(file,...args){if(String(file).includes(record.id+'.json'))throw fault();return write(file,...args);};
  try{const deadline=Date.now()+10000;while(record.status==='running' && Date.now()<deadline)await sleep(25);}
  finally{fs.writeFileSync=write;if(record.status==='running')service.close();}
  assert.equal(record.status,'optimal');assert.ok(record.values);assert.ok(record.persistenceError);assert.equal(service.active,null);
  assert.throws(()=>service.start({engine:'highs',seconds:2,model:demoModel}),{code:'STORAGE_UNAVAILABLE'});
});
test('cancelled model waiter returns promptly without allowing its successor past the active job',async()=>{
  const queue=createModelQueue();let release;const events=[];
  const first=queue(()=>new Promise(r=>{release=r;events.push('first');}));await Promise.resolve();
  const controller=new AbortController(),second=queue(()=>events.push('cancelled-dispatched'),controller.signal);
  const rejected=assert.rejects(second,{name:'AbortError'}),third=queue(()=>events.push('third'));controller.abort();
  await Promise.race([rejected,sleep(500).then(()=>{throw Error('cancel timeout');})]);assert.deepEqual(events,['first']);
  release();await Promise.all([first,third]);assert.deepEqual(events,['first','third']);
});
test('cancelled solver waiter returns promptly and retains FIFO order',async()=>{
  const record={id:'first',status:'running'},events=[];
  const solver={active:null,start:()=>{events.push('start');return events.length===1?record:{id:'third',status:'complete'};},stop:()=>{record.status='stopped';}};
  const first=queuedSolve(solver,{},new AbortController().signal,()=>{});await Promise.resolve();await Promise.resolve();
  const controller=new AbortController(),second=queuedSolve(solver,{},controller.signal,()=>{}),rejected=assert.rejects(second,{name:'AbortError'});
  const third=queuedSolve(solver,{},new AbortController().signal,()=>{});controller.abort();
  await Promise.race([rejected,sleep(500).then(()=>{throw Error('cancel timeout');})]);assert.equal(events.length,1);
  record.status='complete';await Promise.all([first,third]);assert.equal(events.length,2);
});
test('malformed request targets return 400 and the service remains available',async t=>{
  const service=await startServer({directory:directory(),staticDir:path.resolve('dist'),port:0});t.after(()=>service.close());
  const response=await new Promise((resolve,reject)=>{let data='';const socket=net.connect(Number(new URL(service.origin).port),'127.0.0.1',()=>socket.write('GET http://[ HTTP/1.1\r\nHost: '+new URL(service.origin).host+'\r\nConnection: close\r\n\r\n'));socket.setTimeout(2000,()=>socket.destroy(Error('timeout')));socket.on('data',chunk=>data+=chunk);socket.on('error',reject);socket.on('end',()=>resolve(data));});
  assert.match(response,/HTTP\/1.1 400/);assert.equal((await fetch(service.origin+'/api/health')).status,200);
});
test('HTTP save failure returns 503, rolls back state and keeps health/read access available',async t=>{
  const service=await startServer({directory:directory(),staticDir:path.resolve('dist'),port:0});t.after(()=>service.close());
  const headers={'x-fyppppp-token':service.token,'content-type':'application/json'},write=fs.writeFileSync;
  fs.writeFileSync=function(file,...args){if(String(file).startsWith(service.store.file))throw fault();return write(file,...args);};
  let response;try{response=await fetch(service.origin+'/api/conversations',{method:'POST',headers,body:'{}'});}finally{fs.writeFileSync=write;}
  assert.equal(response.status,503);assert.equal((await response.json()).code,'STORAGE_UNAVAILABLE');
  const state=await (await fetch(service.origin+'/api/state',{headers})).json();assert.equal(state.conversations.length,0);assert.ok(state.storageError);
  assert.equal((await fetch(service.origin+'/api/health')).status,200);
  assert.equal((await fetch(service.origin+'/api/conversations',{method:'POST',headers,body:'{}'})).status,503);
});
test('stream persistence failure closes the stream without crashing or dispatching another request',async t=>{
  let resume,entered;const ready=new Promise(r=>entered=r),gate=new Promise(r=>resume=r);let calls=0;
  const service=await startServer({directory:directory(),staticDir:path.resolve('dist'),port:0,
    secretVault:{protect:async x=>x,unprotect:async x=>x},generator:async function*(){calls++;entered();await gate;yield {text:'offline response'};}});t.after(()=>service.close());
  await service.store.configure('openai',{region:'global',model:'offline',apiKey:'fake-key'});const conversation=service.store.create();
  const headers={'x-fyppppp-token':service.token,'content-type':'application/json'};
  const response=await fetch(service.origin+'/api/chat',{method:'POST',headers,body:JSON.stringify({conversationId:conversation.id,provider:'openai',mode:'chat',message:'offline'})});await ready;
  const write=fs.writeFileSync;fs.writeFileSync=function(file,...args){if(String(file).startsWith(service.store.file))throw fault();return write(file,...args);};
  let body;try{resume();body=await response.text();}finally{fs.writeFileSync=write;}
  assert.ok(body.includes('offline response'));assert.ok(service.store.storageError);
  assert.equal((await fetch(service.origin+'/api/health')).status,200);
  assert.equal((await fetch(service.origin+'/api/chat',{method:'POST',headers,body:JSON.stringify({conversationId:conversation.id,provider:'openai',mode:'chat',message:'again'})})).status,503);
  assert.equal(calls,1);
});
