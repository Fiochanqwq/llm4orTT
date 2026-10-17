import crypto from 'node:crypto';

export const agentLimits = Object.freeze({ calls: 4, solves: 2, clarifications: 2, questions: 3, inputCharacters: 24000, modelTokens: 327680, explanationTokens: 327680, seconds: 30 });
export const answerPolicyVersion = '0.6.2-compact-1';
export const executionPolicyVersion = '0.6.4-json-1';
export function stageTokens(config, phase) {
  return Math.min(config.maxTokens, phase === 'modeling' ? (config.modelingTokens ?? 4096) : (config.explanationTokens ?? 768));
}
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
export const inputHash = value => hash(value.trim().replace(/\s+/g, ' '));

// A snapshot belongs to one problem, including follow-up clarification turns.
export function taskFor(conversation, user, retry) {
  const previous = conversation.messages.findLast(m => m.automation?.task)?.automation;
  // A completed answer does not reset the problem budget. New problems use a new conversation.
  if (previous) return structuredClone(previous.task);
  return { id: crypto.randomUUID(), rootUserId: user.id, calls: 0, solves: 0, clarifications: 0, inputs: [], attempts: [], asked: [] };
}

export function taskMessages(conversation, task) {
  // Keep user facts and concise decisions; never replay raw tool dumps or solver logs.
  return conversation.messages.filter(m => m.role === 'user' || m.automation?.task?.id === task.id)
    .flatMap(m => m.role === 'user' ? [{ id: m.id, role: 'user', content: m.content, ...(m.replyTo ? { replyTo: m.replyTo } : {}) }] : m.automation?.decision ? [{ role: 'assistant', content: JSON.stringify({ decision: m.automation.decision, questions: m.automation.questions || [], evidence: m.automation.preflight?.evidence || [] }) }] : []);
}

export function modelFingerprint(model) {
  const terms = value => Object.entries(value).filter(([, v]) => v !== 0).sort(([a], [b]) => a.localeCompare(b));
  return hash(JSON.stringify({ sense: model.sense, variables: model.variables.map(v => ({ name: v.name, type: v.type, lower: v.lower, upper: v.upper })).sort((a, b) => a.name.localeCompare(b.name)), objective: terms(model.objective),
    constraints: model.constraints.map(c => JSON.stringify([terms(c.terms), c.sense, c.rhs])).sort() }));
}

export function decide(answer, code, summary, questions = [], stage = 'clarification') {
  const flow = answer.automation;
  flow.stage = stage; flow.decision = { code, summary }; flow.questions = questions;
  answer.content = summary;
}

export function ask(answer, code, summary, questions, language) {
  const task = answer.automation.task;
  task.asked ||= [];
  const fresh = questions.filter(q => !task.asked.includes(inputHash(q.field + ' ' + q.question)));
  if (!fresh.length) {
    decide(answer, 'repeated_clarification', language === 'en' ? 'This clarification was already requested. Repeated calls are paused. Consolidate the answer before starting a new conversation.' : '已提出过同一澄清问题，停止重复追问。请整理完整条件后新建对话。', [], 'paused'); return;
  }
  if (task.clarifications >= agentLimits.clarifications) {
    decide(answer, 'clarification_budget', language === 'en' ? 'Clarification limit reached. Consolidate the missing conditions and start a new conversation.' : '已达到本题澄清上限。请整理完整条件后新建对话。', [], 'paused');
    return;
  }
  task.clarifications++;
  task.asked.push(...fresh.slice(0, agentLimits.questions).map(q => inputHash(q.field + ' ' + q.question)));
  decide(answer, code, summary, fresh.slice(0, agentLimits.questions));
}

export function reserveCall(answer, messages, language) {
  const flow = answer.automation, en = language === 'en';
  if (flow.task.calls >= agentLimits.calls) {
    decide(answer, 'call_budget', en ? 'Model call limit reached. The saved evidence is available; start a new conversation for a new budget.' : '已达到本题模型调用上限。证据已保存；如需继续，请整理条件后新建对话。', [], 'paused'); return false;
  }
  if (messages.reduce((n, m) => n + m.content.length, 0) > agentLimits.inputCharacters) {
    decide(answer, 'context_budget', en ? 'The problem context exceeds 24,000 characters. Start a new conversation with a shorter, complete description.' : '本题上下文超过 24,000 字符。请将完整条件精简后新建对话。', [], 'paused'); return false;
  }
  // Reserve before dispatch. Failed, cancelled and unknown-usage requests still count.
  flow.task.calls++; return true;
}
