import { executeOptimization as legacy } from './optimization-legacy.mjs';
import { executeV07 } from './optimization-v07.mjs';
import { resultContract, resultText } from '../shared/result-contract.mjs';
import { optimizationTool, optimizationInstructions } from '../shared/optimization-tool.mjs';
export { OptimizationError, solverEvidence, recordContext, explanationMessages } from './optimization-legacy.mjs';
export async function executeOptimization(options) {
  const flow = options.answer.automation;
  if (flow.methods?.structured || flow.methods?.preset==='generic') return executeV07({...options,compact:true});
  const modified=flow.methods?.preset==='generic'?{...options,planner:(config,messages,signal)=>options.planner({...config,tool:optimizationTool,stagePrompt:optimizationInstructions(config.language)+'\nGeneric same-tool harness baseline. No additional semantic audit, budget relevance or automatic repair.'},messages,signal)}:options;
  const record = await legacy(modified);
  if(flow.methods&&flow.plan)flow.methods.modeling='executed';
  if (flow.methods?.delivery && flow.result) {
    const saved = record || options.solver.get(flow.result.id);
    flow.resultContract = resultContract(saved);
    flow.interpretation = 'local_template';
    flow.stage = flow.resultContract.taskOutcome === 'complete' ? 'complete' : 'paused';
    options.answer.content = resultText(flow.resultContract, options.config.language);
    flow.questions = []; flow.decision = {code:'local_result',summary:options.answer.content}; options.update(); return null;
  }
  return record;
}
