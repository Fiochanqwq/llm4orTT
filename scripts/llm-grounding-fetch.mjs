import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const out=path.resolve('datasets/llm-grounding-v1');
fs.mkdirSync(out,{recursive:true});
const files=[
 ['nl4opt/nl4opt-competition','49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea','generation_data/test.jsonl','nl4opt-test.jsonl'],
 ['nl4opt/nl4opt-competition','49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea','LICENSE','NL4OPT-LICENSE'],
 ['optsuite/OptMATH','f15bbc4477c70db85ad148df8bcc1b780bca0f8c','benchmark/OptMATH_Bench.json','OptMATH_Bench.json'],
 ['optsuite/OptMATH','f15bbc4477c70db85ad148df8bcc1b780bca0f8c','LICENSE','OptMATH-LICENSE'],
];
const ledger=fs.existsSync(path.join(out,'download-manifest.json'))?JSON.parse(fs.readFileSync(path.join(out,'download-manifest.json'),'utf8')):[];
for(const [repo,revision,file,name] of files){
 const url=`https://raw.githubusercontent.com/${repo}/${revision}/${file}`;
 const row={name,repo,revision,url,attemptedUtc:new Date().toISOString()};
 try{
  const treeResponse=await fetch(`https://api.github.com/repos/${repo}/git/trees/${revision}?recursive=1`,{signal:AbortSignal.timeout(45000)});
  if(!treeResponse.ok)throw Error('Tree HTTP '+treeResponse.status);
  const tree=await treeResponse.json();
  const blob=tree.tree.find(item=>item.path===file);
  if(!blob)throw Error('Pinned source absent');
  const transportUrl=`https://api.github.com/repos/${repo}/git/blobs/${blob.sha}`;
  row.transportUrl=transportUrl;
  const response=await fetch(transportUrl,{signal:AbortSignal.timeout(45000)});
  if(!response.ok)throw Error('HTTP '+response.status);
  const content=await response.json();
  if(content.encoding!=='base64')throw Error('Unexpected blob encoding');
  const bytes=Buffer.from(content.content,'base64');
  const dest=path.join(out,name);
  if(fs.existsSync(dest)&&!fs.readFileSync(dest).equals(bytes))throw Error('Refusing changed source');
  fs.writeFileSync(dest,bytes);
  Object.assign(row,{status:'downloaded',bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
 }catch(e){Object.assign(row,{status:'failed',error:e.message});}
 ledger.push(row);fs.writeFileSync(path.join(out,'download-manifest.json'),JSON.stringify(ledger,null,2));
 console.log(JSON.stringify(row));
}
