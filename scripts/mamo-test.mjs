import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {solverPython} from '../server/python-runtime.mjs';
const result=spawnSync(solverPython(path.resolve('.')),['-X','utf8','test/mamo-experiment-test.py'],{stdio:'inherit',windowsHide:true});
if(result.error)throw result.error;
process.exitCode=result.status??1;
