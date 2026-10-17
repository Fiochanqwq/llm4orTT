// Transport policy only; agent prompts, budgets and tool schemas belong to the caller.
export const deepseekAdapterVersion = 'deepseek-chat-20261018';
export const deepseekOptions = { thinking: { type: 'enabled' }, reasoning_effort: 'high', stream_options: { include_usage: true } };
export function deepseekUsage(value) {
  const count = x => Number.isFinite(x) && x >= 0 ? x : null;
  return { input: count(value?.prompt_tokens), output: count(value?.completion_tokens) };
}
export function deepseekMetadata(config, responseId, model, finishReason) {
  return { adapter: deepseekAdapterVersion, requestedModel: config.model, returnedModel: model || null,
    responseId: responseId || null, finishReason: finishReason || null, thinking: 'enabled', reasoningEffort: 'high',
    protocol: 'chat_completions', maxOutputTokens: config.maxTokens };
}
