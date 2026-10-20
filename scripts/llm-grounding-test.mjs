// Network-free mathematical tests; no dataset download and no paid API calls.
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {solverPython} from '../server/python-runtime.mjs';
const root=path.resolve('.');
for(const file of ['test/llm-grounding-test.py','test/llm-grounding-stable-test.py']){
 const result=spawnSync(solverPython(root),['-X','utf8',file],{cwd:root,stdio:'inherit',windowsHide:true});
 if(result.error)throw result.error;
 if(result.status!==0){process.exitCode=result.status??1;break;}
}
