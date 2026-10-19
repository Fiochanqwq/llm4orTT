import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { solverPython } from '../server/python-runtime.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=solverPython(root);
const out=path.join(root,'outputs/inverse/pilot-20261019-v3');
async function run(args){await new Promise((resolve,reject)=>{const child=spawn(python,['-X','utf8',...args],{cwd:root,stdio:'inherit',windowsHide:true});child.once('error',reject);child.once('close',code=>code===0?resolve():reject(Error('Research replay failed: '+args.join(' '))));});}
if(process.argv.includes('--test'))await run(['test/research-pilot-test.py']);
else{
 const summaryPath=path.join(out,'summary.json');
 if(!fs.existsSync(summaryPath))throw Error('Offline replay requires the separately archived research results. See research/REPRODUCE.txt.');
 const before=JSON.parse(fs.readFileSync(summaryPath,'utf8'));
 for(const args of [['research/pilot.py','run'],['research/pilot.py','feedback-evaluate'],['research/report.py']])await run(args);
 const after=JSON.parse(fs.readFileSync(path.join(out,'summary.json'),'utf8'));
 const matches=JSON.stringify(before.methods)===JSON.stringify(after.methods)&&JSON.stringify(before.paired)===JSON.stringify(after.paired);
 if(!matches)throw Error('Replayed scores differ from sealed results');
 const result={status:'passed',newModelCalls:0,identicalMethodSummaries:true,identicalPairedScores:true};
 fs.writeFileSync(path.join(out,'replay-verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}
