import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { SolverService } from '../server/solver.mjs';
import { behavioralChecks } from '../server/behavioral.mjs';
const evidence=fs.readdirSync('qa').filter(n=>n.startsWith('v07-examples-')).sort().at(-1);if(!evidence)throw Error('Run verify-v07-examples first');
const directory=path.resolve('qa',evidence),solver=new SolverService(directory);
try{const source=[...solver.jobs.values()].find(r=>r.status==='optimal'&&r.check?.feasible);const result=await behavioralChecks(solver,source,directory,new AbortController().signal);assert.equal(result.rows.length,3);assert.ok(result.rows.every(r=>r.passed===true));console.log(JSON.stringify({source:source.id,analysis:result.id,checks:result.rows.length,directory,providerCalls:0}));}finally{solver.close();}
