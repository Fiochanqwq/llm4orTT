import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Readable } from 'node:stream';
import packageInfo from '../package.json' with {type:'json'};
import { digest } from './experiments.mjs';
const table=Array.from({length:256},(_,n)=>{for(let i=0;i<8;i++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
const crc=buffer=>{let n=0xffffffff;for(const b of buffer)n=table[(n^b)&255]^(n>>>8);return(n^0xffffffff)>>>0;};
export function analysisRow(run){
  const flow=run.conversation?.messages.findLast(m=>m.automation)?.automation;
  const requests=run.events?.filter(e=>['reserved','sent','completed','failed','cancelled_unknown','interrupted_unknown'].includes(e.state))||[];
  return clean({kind:'run_summary',schema:'llm4orovo.analysis.v1',id:run.id,runId:run.id,batchId:run.batchId,caseId:run.caseId,caseHash:run.caseHash,baseId:run.baseId,preset:run.preset,repeat:run.repeat,entry:run.entry??'workbench',
    publicPrompt:run.publicPrompt??null,answer:run.conversation?.messages.findLast(m=>m.role==='assistant')?.content??null,solverResult:flow?.resultContract??null,solverRunId:flow?.runId??flow?.result?.id??null,
    frozen:run.frozen,sourceSnapshot:run.sourceSnapshot??null,environmentVersion:run.environmentVersion,scorerVersion:run.score?.independent?.version,status:run.status,failure:run.failure??null,environmentFailure:run.environmentFailure??null,
    score:run.score??null,manualVerdict:run.manualVerdict??null,createdAt:run.createdAt,completedAt:run.completedAt,
    durationMs:run.completedAt&&run.createdAt?Date.parse(run.completedAt)-Date.parse(run.createdAt):null,
    requests:requests.map(r=>({id:r.id,stage:r.stage,state:r.state,promptHash:r.promptHash??null,usage:r.response?.usage??null,rawUsage:r.response?.rawUsage??null,requestMetadata:r.response?.requestMetadata??null,httpStatus:r.httpStatus??null,createdAt:r.createdAt,completedAt:r.completedAt??null})),
    calls:flow?.task?.calls??run.nativeCalls??requests.length,solves:flow?.task?.solves??0,clarifications:flow?.task?.clarifications??run.environmentTurns??0,
    protocolCorrections:flow?.task?.protocolCorrections??0,semanticRepairs:flow?.task?.semanticRepairs??0,unknownUsageRequests:requests.filter(r=>r.response?.usage?.input==null||r.response?.usage?.output==null).length});
}
export function readStoredZip(buffer){
  if(buffer.length>64*1024*1024)throw Error('输入归档超过 64 MB');let offset=0;const entries=[];
  while(offset+4<=buffer.length&&buffer.readUInt32LE(offset)===0x04034b50){
    if(offset+30>buffer.length)throw Error('输入归档截断');const flags=buffer.readUInt16LE(offset+6),method=buffer.readUInt16LE(offset+8),sum=buffer.readUInt32LE(offset+14),size=buffer.readUInt32LE(offset+18),uncompressed=buffer.readUInt32LE(offset+22),len=buffer.readUInt16LE(offset+26),extra=buffer.readUInt16LE(offset+28),start=offset+30+len+extra;
    if(flags!==0||method!==0||size!==uncompressed||size>8*1024*1024||start+size>buffer.length||entries.length>=12000)throw Error('不支持的压缩格式或输入大小无效');
    const name=buffer.subarray(offset+30,offset+30+len).toString(),data=buffer.subarray(start,start+size);if(crc(data)!==sum)throw Error('输入归档校验失败');entries.push({name,data:JSON.parse(data.toString('utf8'))});offset=start+size;
  }
  if(!entries.length||offset+4>buffer.length||buffer.readUInt32LE(offset)!==0x02014b50)throw Error('输入 ZIP 目录无效');
  return {format:'llm4orovo.bundle.v2',schemaVersion:2,entries};
}
function clean(value, redact=false, parent='',includePrivate=false){
  if(Array.isArray(value))return value.map(v=>clean(v,redact,parent,includePrivate));
  if(value&&typeof value==='object'){
    if(parent==='independent'&&!includePrivate){const {evidence,referenceProvenance,...publicScore}=value;value={...publicScore,evidence:(evidence||[]).map(e=>({code:e.code}))};}
    return Object.fromEntries(Object.entries(value).filter(([k])=>['objective','terms','values','displayValues','costTerms'].includes(parent)||!/^(apiKey|encryptedKey|authorization|accessToken|token|secret|privateCard|privateReference)$/i.test(k)).map(([k,v])=>[k,clean(v,redact,k,includePrivate)]));
  }
  if(typeof value==='string'&&redact)return value.replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g,'[REDACTED]').replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,'[EMAIL]');
  return value;
}
export function conversationExport(conversations,solver,{redact=false}={}){
  const ids=[...new Set(conversations.flatMap(c=>c.messages.flatMap(m=>[m.solverRunId,m.provenance?.solverRun?.id,m.automation?.runId,m.automation?.result?.id,...(m.automation?.task?.attempts||[]).map(a=>a.runId)]).filter(Boolean)))];
  const behavioralAnalyses=[];
  const analysisDirectory=solver.directory&&path.join(path.dirname(solver.directory),'behavioral');
  if(analysisDirectory&&fs.existsSync(analysisDirectory))for(const name of fs.readdirSync(analysisDirectory).filter(n=>/^[a-f0-9-]{36}\.json$/.test(n))){const analysis=JSON.parse(fs.readFileSync(path.join(analysisDirectory,name),'utf8'));if(ids.includes(analysis.sourceRunId)){behavioralAnalyses.push(analysis);for(const row of analysis.rows||[])if(row.runId&&!ids.includes(row.runId))ids.push(row.runId);}}
  const solverRuns=ids.map(id=>solver.get(id)).filter(Boolean);
  return clean({format:'llm4orovo.export.v2',schemaVersion:2,version:2,appVersion:packageInfo.version,kind:'conversation',exportedAt:new Date().toISOString(),
    complete:!conversations.some(c=>c.messages.some(m=>m.status==='streaming'))&&!solverRuns.some(r=>r.status==='running'),
    conversations,solverRuns,behavioralAnalyses,missingSolverRunIds:ids.filter(id=>!solver.get(id)),legacyReviewPolicy:'Absent reviews remain absent; never inferred.'},redact);
}
function* zip(entries){let offset=0;const central=[];
  for(const entry of entries){const name=Buffer.from(entry.name),data=fs.readFileSync(entry.path),sum=crc(data),head=Buffer.alloc(30);head.writeUInt32LE(0x04034b50);head.writeUInt16LE(20,4);head.writeUInt32LE(sum,14);head.writeUInt32LE(data.length,18);head.writeUInt32LE(data.length,22);head.writeUInt16LE(name.length,26);
    const cd=Buffer.alloc(46);cd.writeUInt32LE(0x02014b50);cd.writeUInt16LE(20,4);cd.writeUInt16LE(20,6);cd.writeUInt32LE(sum,16);cd.writeUInt32LE(data.length,20);cd.writeUInt32LE(data.length,24);cd.writeUInt16LE(name.length,28);cd.writeUInt32LE(offset,42);central.push(cd,name);
    yield head;yield name;yield data;offset+=head.length+name.length+data.length;
  }
  const size=central.reduce((n,b)=>n+b.length,0);yield*central;const end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(entries.length,8);end.writeUInt16LE(entries.length,10);end.writeUInt32LE(size,12);end.writeUInt32LE(offset,16);yield end;
}
export class ExportService {
  constructor(directory,store,solver,experiments){this.directory=path.join(directory,'exports');fs.mkdirSync(this.directory,{recursive:true});this.store=store;this.solver=solver;this.experiments=experiments;this.tickets=new Map();this.sweep();}
  purge(token){(function remove(target){let stat;try{stat=fs.lstatSync(target);}catch{return;}if(stat.isDirectory()&&!stat.isSymbolicLink()){for(const name of fs.readdirSync(target))remove(path.join(target,name));try{fs.rmdirSync(target);}catch{}}else{try{fs.chmodSync(target,0o666);}catch{}try{fs.unlinkSync(target);}catch{}}})(path.join(this.directory,token));}
  // Tickets live in memory only, so any staging directory left on disk at startup is garbage.
  sweep(){try{for(const name of fs.readdirSync(this.directory))if(/^[a-f0-9]{64}$/.test(name))this.purge(name);}catch{}}
  imports(){return fs.readdirSync(this.directory).filter(x=>/^import-[a-f0-9-]{36}\.json$/.test(x)).map(name=>{const value=JSON.parse(fs.readFileSync(path.join(this.directory,name),'utf8'));return {id:value.id,status:value.status,importedAt:value.importedAt,legacy:!!value.legacy};});}
  imported(id){if(!/^[a-f0-9-]{36}$/.test(id))throw Error('请求归档标识无效');const file=path.join(this.directory,'import-'+id+'.json');return fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):null;}
  importedCases(id){const value=this.imported(id);if(!value)throw Error('请求归档不存在');const cases=[];
    if(value.legacy){for(const c of value.data.conversations){const prompt=c.messages.find(m=>m.role==='user')?.content;if(prompt)cases.push({id:c.id||crypto.randomUUID(),prompt});}}
    else for(const entry of value.data.entries||[]){if(entry.name.startsWith('batches/'))for(const c of entry.data.cases||[])if(!cases.some(x=>x.id===c.id))cases.push({id:c.id,prompt:c.prompt,baseId:c.baseId});if(entry.name.startsWith('conversations/'))for(const c of entry.data.conversations||[]){const prompt=c.messages.find(m=>m.role==='user')?.content;if(prompt)cases.push({id:c.id,prompt});}}
    return cases;
  }
  create(selection){
    for(const field of ['conversationIds','batchIds','runIds'])if(selection[field]!==undefined&&(!Array.isArray(selection[field])||selection[field].length>10000||selection[field].some(id=>typeof id!=='string'||!/^[a-f0-9-]{36}$/.test(id))))throw Error('请选择有效导出范围');
    const format=selection.format||'json';if(!['json','jsonl','zip'].includes(format))throw Error('请选择有效导出格式');
    const token=crypto.randomBytes(32).toString('hex'),directory=path.join(this.directory,token);fs.mkdirSync(directory);
    const entries=[],manifest={format:'llm4orovo.archive.v2',schemaVersion:2,appVersion:packageInfo.version,exportedAt:new Date().toISOString(),complete:true,privateIncluded:selection.includePrivate===true,redacted:selection.redact===true,cutoffs:[],missingReferences:[],files:[]};
    const write=(name,value)=>{const data=Buffer.from(JSON.stringify(value,null,2)),file=path.join(directory,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,data);entries.push({name,path:file});manifest.files.push({name,sha256:digest(data.toString()),bytes:data.length,encoding:'json-pretty-2'});};
    const conversations=selection.conversationIds===undefined?[]:this.store.data.conversations.filter(c=>selection.conversationIds.includes(c.id));
    for(const c of conversations){const exported=conversationExport([c],this.solver,{redact:selection.redact});manifest.complete&&=exported.complete;manifest.missingReferences.push(...exported.missingSolverRunIds);write('conversations/'+c.id+'.json',exported);}
    for(const id of selection.batchIds||[]){const b=this.experiments.batches.get(id);if(!b)throw Error('请求实验不存在');manifest.cutoffs.push({batchId:id,sequence:b.sequence});manifest.complete&&=!b.runs.some(r=>['running','queued'].includes(r.status));
      const selected=selection.runIds?b.runs.filter(r=>selection.runIds.includes(r.id)):b.runs;if(!selected.length)throw Error('请选择有效运行记录');
      const metadata=clean(b,selection.redact,'',selection.includePrivate===true);delete metadata.privateCardHash;metadata.runs=clean(selected,selection.redact,'',selection.includePrivate===true);metadata.cases=metadata.cases.filter(c=>selected.some(r=>r.caseId===c.id));
      if(selection.includePrivate===true){metadata.privateCards=b.cases.filter(c=>selected.some(r=>r.caseId===c.id)).map(c=>({caseId:c.id,card:clean(c.privateCard,selection.redact)}));metadata.privateReferences=b.cases.filter(c=>selected.some(r=>r.caseId===c.id)).map(c=>({caseId:c.id,reference:clean(c.privateReference,selection.redact)}));}
      write('batches/'+id+'.json',metadata);
      for(const meta of selected){const run=this.experiments.run(meta.id);if(run){const snapshot=clean(run,selection.redact,'',selection.includePrivate===true),evidence=conversationExport([run.conversation],this.solver,{redact:selection.redact});snapshot.solverEvidence=evidence.solverRuns;snapshot.behavioralAnalyses=evidence.behavioralAnalyses;snapshot.missingSolverRunIds=evidence.missingSolverRunIds;manifest.missingReferences.push(...evidence.missingSolverRunIds);manifest.cutoffs.push({runId:run.id,sequence:run.sequence});write('runs/'+run.id+'.json',snapshot);}else manifest.missingReferences.push(meta.id);}
    }
    if(!entries.length)throw Error('请选择导出内容');
    fs.writeFileSync(path.join(directory,'manifest.json'),JSON.stringify(manifest));entries.unshift({name:'manifest.json',path:path.join(directory,'manifest.json')});
    this.tickets.set(token,{entries,format,expires:Date.now()+60000});return {url:'/api/download/'+token,filename:'llm4orOvO-'+Date.now()+'.'+format,manifest};
  }
  download(token,res){const ticket=this.tickets.get(token);this.tickets.delete(token);if(!ticket||ticket.expires<Date.now())return false;
    const {entries,format}=ticket;res.writeHead(200,{'Content-Type':format==='zip'?'application/zip':format==='jsonl'?'application/x-ndjson':'application/json','Content-Disposition':`attachment; filename="llm4orOvO-export.${format}"`,'Cache-Control':'no-store'});
    const iterable=format==='zip'?zip(entries):(function*(){if(format==='json')yield '{"format":"llm4orovo.bundle.v2","schemaVersion":2,"entries":[';let first=true;for(const e of entries){const data=fs.readFileSync(e.path,'utf8');if(format==='json'){if(!first)yield ',';yield '{"name":'+JSON.stringify(e.name)+',"data":'+data+'}';}
      else {const value=JSON.parse(data);if(e.name==='manifest.json')yield JSON.stringify({kind:'manifest',...value})+'\n';else if(e.name.startsWith('runs/'))yield JSON.stringify(analysisRow(value))+'\n';else if(e.name.startsWith('conversations/'))yield JSON.stringify({kind:'conversation_summary',id:value.conversations[0].id,messages:value.conversations[0].messages.length,complete:value.complete})+'\n';}first=false;}if(format==='json')yield ']}';})();
    const stream=Readable.from(iterable);let released=false;const release=()=>{if(released)return;released=true;stream.destroy();this.purge(token);};
    stream.on('error',()=>{try{res.destroy();}catch{}release();});res.on('close',release);res.on('finish',release);stream.pipe(res);return true;
  }
  import(data){
    if(data?.format==='llm4orovo.summary.v2'){
      if(!Array.isArray(data.rows)||!data.rows.length||data.rows.length>12000||data.rows.some(r=>!['manifest','run_summary','conversation_summary'].includes(r.kind)))throw Error('输入摘要格式无效');
      const id=crypto.randomUUID();fs.writeFileSync(path.join(this.directory,'import-'+id+'.json'),JSON.stringify({id,status:'historical_only',summaryOnly:true,importedAt:new Date().toISOString(),data:clean(data)}));return {id,status:'historical_only',summaryOnly:true,entries:data.rows.length};
    }
    if(data?.version===1&&Array.isArray(data.conversations)){
      if(data.conversations.length>1000||data.conversations.some(c=>!Array.isArray(c.messages)||c.messages.length>10000||c.messages.some(m=>!['user','assistant'].includes(m.role)||typeof m.content!=='string'||m.content.length>1000000)))throw Error('输入旧版对话格式无效');
      const id=crypto.randomUUID();fs.writeFileSync(path.join(this.directory,'import-'+id+'.json'),JSON.stringify({id,status:'historical_only',legacy:true,importedAt:new Date().toISOString(),data:clean(data)}));return {id,status:'historical_only',entries:data.conversations.length,legacy:true};
    }
    if(!data||data.format!=='llm4orovo.bundle.v2'||data.schemaVersion!==2||!Array.isArray(data.entries)||data.entries.length>12000)throw Error('不支持的导入格式：需要 v2 JSON bundle');
    const names=new Set();for(const e of data.entries){if(typeof e.name!=='string'||!(/^(manifest\.json|(?:runs|batches|conversations)\/[a-f0-9-]{36}\.json)$/.test(e.name))||names.has(e.name))throw Error('输入路径或重复条目无效');names.add(e.name);}
    const manifest=data.entries.find(e=>e.name==='manifest.json')?.data;if(manifest?.schemaVersion!==2||!Array.isArray(manifest.files))throw Error('输入清单缺失');
    if(new Set(manifest.files.map(f=>f.name)).size!==manifest.files.length)throw Error('输入清单重复');
    for(const file of manifest.files){const entry=data.entries.find(e=>e.name===file.name),serialized=entry&&JSON.stringify(entry.data,null,file.encoding==='json-pretty-2'?2:undefined);if(!entry||digest(serialized)!==file.sha256||Buffer.byteLength(serialized)!==file.bytes)throw Error('输入文件哈希或长度不匹配');}
    if(manifest.files.length!==data.entries.length-1)throw Error('输入包含未登记文件');
    const declaredMissing=new Set(manifest.missingReferences||[]);
    for(const entry of data.entries.filter(e=>e.name.startsWith('batches/'))){if(!Array.isArray(entry.data.runs))throw Error('输入实验索引无效');for(const run of entry.data.runs)if(!names.has('runs/'+run.id+'.json')&&!declaredMissing.has(run.id))throw Error('输入运行引用缺失');}
    const id=crypto.randomUUID(),file=path.join(this.directory,'import-'+id+'.json');fs.writeFileSync(file,JSON.stringify({id,status:'historical_only',importedAt:new Date().toISOString(),data:clean(data)}));return {id,status:'historical_only',entries:data.entries.length};
  }
}
