// Transport policy only; agent prompts, budgets and tool schemas belong to the caller.
export const deepseekAdapterVersion = 'deepseek-compatible-20261019';
// Keep the exact requested ID: old checkpoints may be hosted by a compatible gateway.
// Unknown models receive only standard Chat Completions fields, so new versions are usable
// without first updating a hard-coded allowlist.
export function deepseekRequest(config) {
  const model = config.model.toLowerCase().split('/').at(-1);
  const modern = /^deepseek-(?:flash(?:$|[-.])|v4(?:$|[-.]))/.test(model);
  const reasoner = /^deepseek-(?:reasoner|r1)(?:$|[-.])/.test(model);
  const legacyChat = /^deepseek-(?:chat|coder|v[23])(?:$|[-.])/.test(model);
  const limit = modern ? 393216 : reasoner ? 65536 : legacyChat ? 4096 : null;
  const maxTokens = limit ? Math.min(config.maxTokens, limit) : config.maxTokens;
  const economy = modern && config.economy === true;
  return {
    options: { max_tokens: maxTokens, ...(modern ? {
      thinking: { type: economy ? 'disabled' : 'enabled' }, ...(economy ? {} : { reasoning_effort: 'high' }), stream_options: { include_usage: true }
    } : {}) },
    profile: economy ? 'modern-economy' : modern ? 'modern-thinking' : reasoner ? 'legacy-reasoner' : legacyChat ? 'legacy-chat' : 'compatible',
    thinking: economy ? 'disabled' : modern || reasoner ? 'enabled' : 'server-default',
    reasoningEffort: modern && !economy ? 'high' : null,
    maxTokens
  };
}
export function deepseekUsage(value) {
  const count = x => Number.isFinite(x) && x >= 0 ? x : null;
  return { input: count(value?.prompt_tokens), output: count(value?.completion_tokens) };
}
export function deepseekMetadata(config, responseId, model, finishReason) {
  const request = deepseekRequest(config);
  return { adapter: deepseekAdapterVersion, requestedModel: config.model, returnedModel: model || null,
    responseId: responseId || null, finishReason: finishReason || null, profile: request.profile,
    thinking: request.thinking, reasoningEffort: request.reasoningEffort,
    protocol: 'chat_completions', requestedMaxOutputTokens: config.maxTokens, maxOutputTokens: request.maxTokens };
}
