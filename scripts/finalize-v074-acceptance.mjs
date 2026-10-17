import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {readBatchConfig} from './run-experiments.mjs';
import {compactPrompt,compactReviewPrompt} from '../shared/compact-protocol.mjs';
import {researchPrompt,reviewPrompt} from '../baselines/0.7.3-research-20261013/shared/research-tool.mjs';
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const latest=(prefix,predicate=()=>true)=>fs.readdirSync('qa').filter(n=>n.startsWith(prefix)&&fs.existsSync(`qa/${n}/report.json`)).sort().reverse().map(n=>({file:`qa/${n}/report.json`,data:read(`qa/${n}/report.json`)})).find(x=>predicate(x.data));
const integration=latest('v074-integration-'),packaged=latest('desktop-v074-'),desktop=latest('desktop-',d=>d.executablePath?.includes('0.7.4')),artifact=latest('artifact-',d=>d.artifacts?.some(a=>a.file.includes('0.7.4'))),references=latest('v074-references-');
assert.equal(integration.data.checks.length,6);assert.deepEqual(integration.data.errors,[]);
for(const x of [packaged,desktop,artifact])assert.equal(x.data.status,'passed');
assert.equal(references.data.controls,16);
const tests=fs.readFileSync('qa-v074-tests-final-2.log','utf8');assert.match(tests,/pass 163/);assert.match(tests,/fail 0/);
const baselineRoot='baselines/0.7.3-research-20261013',baseline=read(baselineRoot+'/manifest.json');
for(const f of baseline.files)assert.equal(hash(baselineRoot+'/'+f.path),f.sha256,'Frozen baseline changed: '+f.path);
const historyRoot='experiments/protocol-regression-20261013',history=read(historyRoot+'/manifest.json');
for(const f of history.records)assert.equal(hash(historyRoot+'/'+f.path),f.sha256,'Historical response changed: '+f.path);
const prior=read('qa/v073-acceptance.json'),priorInstaller=prior.artifact.artifacts.find(a=>a.file.endsWith('.exe')&&a.file.includes('Setup'));
assert.equal(hash(priorInstaller.file),priorInstaller.sha256);
const reviewedBatch=read('logs/export_review_20261013/audit.json');assert.equal(hash(reviewedBatch.source),reviewedBatch.sha256,'Reviewed 0.7.3 export changed');
const extracted='qa/v074-installer-recheck/resources/app.asar',asar='release/0.7.4/win-unpacked/resources/app.asar';assert.equal(hash(extracted),hash(asar));
const walk=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(dir+'/'+e.name):[dir+'/'+e.name]);
const files=[...['server','shared','src','electron','solver','scripts','test','docs'].flatMap(walk).filter(f=>!f.includes('__pycache__')&&!f.endsWith('.pyc')),'package.json','package-lock.json','vite.config.ts','tsconfig.json','index.html'].map(file=>({file,sha256:hash(file),bytes:fs.statSync(file).size}));
fs.writeFileSync('qa/v074-source-manifest.json',JSON.stringify({version:'0.7.4',createdAt:new Date().toISOString(),files},null,2));
const promptBurden={metric:'characters_in_system_prompt_only_not_tokens_or_performance',oldModeling:researchPrompt('zh-CN',true).length,newModeling:compactPrompt('zh-CN',{structured:true,budget:true}).length,oldReview:reviewPrompt('zh-CN').length,newReview:compactReviewPrompt('zh-CN').length};
const draft=readBatchConfig('experiments/v074-development/pilot.json').summary;
const report={version:'0.7.4',methodVersion:'0.7.4-research-1',createdAt:new Date().toISOString(),engineeringAcceptance:'passed_for_named_cases',taskStatus:{P0:'complete',P1:'complete',P2:'complete',P3:'complete',P4:'complete',P5:'not_started_configuration_and_fee_freeze_pending'},
 tests:{total:163,passed:163,failed:0,newTargeted:20,log:'qa-v074-tests-final-2.log',earlierFailureLog:'qa-v074-tests-final.log',earlierFailureCause:'OpenBLAS allocation failure in concurrent test processes; numerical library threads bounded to 1 and entire suite repeated'},
 before:{file:'qa/v074-before.json',cases:read('qa/v074-before.json').results.length},
 reports:{integration:integration.file,packagedResearch:packaged.file,desktop:desktop.file,artifact:artifact.file,references:references.file,visual:path.dirname(integration.file)+'/visual-recheck.json'},
 softwareEvidence:{integrationChecks:integration.data.checks.length,pairedInjectedTrajectories:integration.data.pairedSoftwareTrajectories,integrationInjectedPlannerCalls:integration.data.injectedPlannerCalls,integrationRealSolves:integration.data.realSolverRuns,packagedResearchChecks:packaged.data.checks,packagedInjectedPlannerCalls:packaged.data.totalPlannerCalls,packagedRealSolves:packaged.data.realSolves,desktopChecks:desktop.data.checks.length,referenceSolverControls:references.data.controls,historicalReplayFailures:read('qa/v071-recorded-replay.json').oldFailures},
 artifact:{filesMatched:artifact.data.matches.length,runtimeFilesMatched:artifact.data.runtimeMatches.length,artifacts:artifact.data.artifacts,installerPayloadMatchesTestedProgram:true,asarSha256:hash(asar),installationWizardRun:false},
 preservation:{baseline:baselineRoot+'/manifest.json',baselineFilesVerified:baseline.files.length,historicalResponsesUnchanged:history.records.length,priorInstaller,latestReviewedBatch:{batchId:reviewedBatch.batchId,source:reviewedBatch.source,sha256:reviewedBatch.sha256}},
 protocol:'docs/research-protocol-v074.json',sourceManifest:'qa/v074-source-manifest.json',sourceFiles:files.length,promptBurden,pilot:{...draft,status:'draft_not_started',referenceFileHash:hash('experiments/v074-development/references.private.json')},newRealProviderCalls:0,
 limits:['Finite budget-language adapter; ambiguous requests need human review','Independent scoring leaves unknown variable mapping, text extraction, explanation and units for review','Q semantic premises are not proved by boolean fields or reference coverage','No new live provider reliability, method benefit or token/cost claim','Isolated packaged executable and installer payload checked; user installation and data were not overwritten'],
 logs:['qa-v074-tests-final-2.log','qa-v074-build.log','qa-v074-integration-final.log','qa-v074-package.log','qa-v074-packaged-research.log','qa-v074-desktop.log','qa-v074-artifact.log','qa-v074-installer-extract.log'].map(file=>({file,sha256:hash(file)}))};
assert.equal(report.pilot.trajectories,96);assert.equal(report.pilot.maximumRequests,384);
fs.writeFileSync('qa/v074-acceptance.json',JSON.stringify(report,null,2));
console.log(JSON.stringify({status:report.engineeringAcceptance,tests:report.tests.total,desktopChecks:report.softwareEvidence.desktopChecks,packagedChecks:report.softwareEvidence.packagedResearchChecks,baselineFiles:baseline.files.length,unchangedHistoricalRecords:history.records.length,sourceFiles:files.length,promptBurden,installer:report.artifact.artifacts.at(-1),providerCalls:0}));
