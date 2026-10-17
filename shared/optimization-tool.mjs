import { demoModel, demoProblem } from './solver-model.mjs';

export const optimizationTool = {
  name: 'submit_optimization',
  description: 'Submit a linear/mixed-integer optimization model for actual local execution, or ask for missing information. Never calculate the solution yourself.',
  parameters: {
    type: 'object', additionalProperties: false,
    properties: {
      action: { type: 'string', enum: ['solve', 'clarify', 'unsupported'] },
      model_json: { type: 'string', description: 'For solve, a JSON-encoded llm4orovo.lp.v1 model; otherwise the empty string. Data only, never executable code.' },
      message: { type: 'string', description: 'A brief decision summary, at most 600 characters. For clarify state what blocks modeling; for solve describe the model. Never give a numerical solution or a private reasoning transcript.' },
      questions: { type: 'array', description: 'For clarify only: 1 to 3 essential questions, ordered by impact. Otherwise empty.', items: {
        type: 'object', additionalProperties: false, properties: {
          field: { type: 'string', description: 'Short name of the missing or conflicting condition, up to 80 characters.' },
          question: { type: 'string', description: 'One targeted question, up to 240 characters.' },
          impact: { type: 'string', description: 'What model decision depends on this answer, up to 160 characters.' }
        }, required: ['field', 'question', 'impact']
      } }
    },
    required: ['action', 'model_json', 'message', 'questions']
  }
};

export function optimizationInstructions(language) {
  return `You are the modeling stage of a local optimization application. Reply ${language === 'en' ? 'in English' : 'in Chinese'} unless requested otherwise.
Call submit_optimization exactly once. Do not answer or solve the problem in prose. The application will validate and execute the submitted model using Pyomo and a real solver.
Use solve only when sufficient information defines an LP/MILP. Use clarify for missing or ambiguous objective, coefficients, units, domains or constraints. Do not invent data. Use unsupported for requests outside LP/MILP, or general discussion (suggest switching to Chat mode). Nonlinear expressions and arbitrary Python are not supported.
Ask at most three questions together and only if their answers can change the feasible set, objective, units or tool choice. Reuse facts already supplied. Do not ask about presentation preferences or seek confirmation of explicit conditions. Do not repeat answered questions. If a previous failure is supplied, inspect that evidence and request only the missing correction. Do not silently weaken constraints, change numbers or enumerate alternative models. Supply a brief decision summary and actionable evidence, not a step-by-step private chain of thought. Questions must be empty for solve/unsupported.
model_json must contain exactly format, name, sense, variables, objective, constraints, as in the example. sense: maximize/minimize; variables: continuous/integer/binary with explicit lower/upper (null = unbounded, binary bounds 0/1). Names: ASCII letter followed by letters/digits/underscores, max 40 characters. Objective/terms: sparse coefficient objects keyed by variable names. Constraints: name, terms, sense (<=, >=, =), rhs. Limits: 200 variables, 500 constraints, 20000 coefficients, finite magnitudes <= 1e9. Each expression needs a nonzero coefficient. Do not add a solution, executable code or extra fields.
This is a FORMAT EXAMPLE, not the user's problem:
${demoProblem.en}
${JSON.stringify(demoModel)}
Model the actual latest user request with relevant prior context. A prior solution does not replace a fresh local solve.`;
}
