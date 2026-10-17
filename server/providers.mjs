import { deepseekOptions, deepseekUsage, deepseekMetadata } from './deepseek.mjs';
import OpenAI from 'openai';
import Anthropic from '@anthropic-ai/sdk';
import { GoogleGenAI } from '@google/genai';
import { catalog } from './store.mjs';
import { optimizationTool, optimizationInstructions } from '../shared/optimization-tool.mjs';
function instructionsFor(language) {
  return language === 'en'
    ? 'You are a resource allocation and mathematical optimization assistant. Reply in clear English unless the user requests another language. Use formulas and code when helpful, and clarify ambiguities. Without actual tool output, never claim to have executed code, run a solver, or verified a result. Do not invent successful checks, experimental results, or performance improvements.'
    : '你是资源分配与数学优化助手。默认使用清晰中文，用户指定其他语言时遵循其要求。必要时使用数学公式和代码。遇到歧义时澄清。没有实际工具输出时，不得声称执行了代码、求解器或验证；不虚构检查通过、实验结果或性能提升。';
}
export function readableError(error) {
  if (error?.name === 'AbortError' || /abort/i.test(error?.name || '')) return '生成已停止';
  const status = Number(error?.status || error?.statusCode || error?.error?.code);
  if (status === 401) return '密钥无效，或与所选地区不匹配';
  if (status === 402) return 'DeepSeek 账户余额不足，请充值后重试';
  if (status === 403) return '当前账户没有访问权限，请检查地区与模型权限';
  if (status === 404) return '模型或接口地址不存在，请检查模型 ID 与地区';
  if (status === 429) return '请求过于频繁或额度不足，请查看厂商控制台后重试';
  if (status === 400 || status === 422) return '此模型不支持当前请求，请检查模型 ID、参数和上下文长度';
  if (status >= 500) return '模型服务暂时不可用，请稍后重试';
  if (/密钥|Windows|保护/.test(error?.message || '') && !/sk-|Bearer/i.test(error.message)) return error.message;
  return '连接失败，请检查网络、接口地址与模型配置';
}
function openai(config, fetchImpl) { return new OpenAI({ apiKey: config.apiKey, baseURL: config.baseURL, maxRetries: 0, timeout: 120000, ...(fetchImpl ? { fetch: fetchImpl } : {}) }); }
function anthropic(config, fetchImpl) { return new Anthropic({ apiKey: config.apiKey, baseURL: config.baseURL, maxRetries: 0, timeout: 120000, ...(fetchImpl ? { fetch: fetchImpl } : {}) }); }
function gemini(config) { return new GoogleGenAI({ apiKey: config.apiKey, httpOptions: { baseUrl: config.baseURL, timeout: 120000 } }); }
// This first stage returns tool arguments only. Its prose is never streamed as a solved answer.
// Interpretation is a separate, stateless text request with server-supplied solver data;
// no partial reasoning/tool transcript is replayed across incompatible provider protocols.
export async function planOptimization(config, messages, signal, dependencies = {}) {
  const instructions = config.stagePrompt ?? optimizationInstructions(config.language), tool = config.tool ?? optimizationTool;
  const common = messages.map(m => ({ role: m.role, content: m.content }));
  let response, calls, text, usage, truncated, responseId, returnedModel, finishReason, rawUsage = null;
  if (config.id === 'openai') {
    response = await openai(config, dependencies.fetch).responses.create({ model: config.model, instructions, input: common, max_output_tokens: config.maxTokens, store: false,
      tools: [{ type: 'function', ...tool, strict: tool.strict ?? true }], tool_choice: { type: 'function', name: tool.name }, parallel_tool_calls: false }, { signal });
    calls = (response.output || []).filter(x => x.type === 'function_call').map(x => ({ id: x.call_id, name: x.name, arguments: x.arguments }));
    text = response.output_text || ''; truncated = response.status !== 'completed'; responseId = response.id;
    usage = { input: response.usage?.input_tokens ?? null, output: response.usage?.output_tokens ?? null };
  } else if (config.id === 'anthropic') {
    response = await anthropic(config, dependencies.fetch).messages.create({ model: config.model, max_tokens: config.maxTokens, system: instructions, messages: common,
      tools: [{ name: tool.name, description: tool.description, input_schema: tool.parameters }], tool_choice: { type: 'auto', disable_parallel_tool_use: true } }, { signal });
    calls = (response.content || []).filter(x => x.type === 'tool_use').map(x => ({ id: x.id, name: x.name, arguments: x.input }));
    text = (response.content || []).filter(x => x.type === 'text').map(x => x.text).join(''); truncated = response.stop_reason === 'max_tokens'; responseId = response.id;
    usage = { input: response.usage?.input_tokens ?? null, output: response.usage?.output_tokens ?? null };
  } else if (config.id === 'gemini') {
    response = await (dependencies.google || gemini(config)).models.generateContent({ model: config.model, contents: common.map(m => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] })), config: {
      systemInstruction: instructions, maxOutputTokens: config.maxTokens, abortSignal: signal,
      tools: [{ functionDeclarations: [{ name: tool.name, description: tool.description, parametersJsonSchema: tool.parameters }] }],
      toolConfig: { functionCallingConfig: { mode: 'ANY', allowedFunctionNames: [tool.name] } }
    } });
    const parts = response.candidates?.[0]?.content?.parts || [];
    calls = parts.filter(x => x.functionCall).map(x => ({ id: x.functionCall.id || null, name: x.functionCall.name, arguments: x.functionCall.args }));
    text = parts.filter(x => x.text && !x.thought).map(x => x.text).join(''); truncated = response.candidates?.[0]?.finishReason !== 'STOP'; responseId = response.responseId;
    usage = { input: response.usageMetadata?.promptTokenCount ?? null, output: response.usageMetadata?.candidatesTokenCount ?? null };
  } else {
    const glmSettings = config.id === 'glm' && /^glm-5\.3/.test(config.model) ? { reasoning_effort: 'low' } : {};
    // This is a fresh planning request, not a continuation of a provider tool
    // transcript. DeepSeek thinking mode requires reasoning for assistant turns;
    // represent the application's fact/decision history as input data instead.
    const planningMessages = config.id === 'deepseek' ? [{ role: 'user', content: 'Application conversation history (ordered facts and decisions; model the latest request):\n' + JSON.stringify(common) }] : common;
    // Auto is compatible with thinking models and GLM. The server requires one valid call;
    // a plain-text answer never bypasses execution, even when the provider ignores the prompt.
    const stream = await openai(config, dependencies.fetch).chat.completions.create({ model: config.model, messages: [{ role: 'system', content: instructions }, ...planningMessages], max_tokens: config.maxTokens,
      tools: [{ type: 'function', function: tool }], tool_choice: 'auto', stream: true, ...(config.id === 'deepseek' ? deepseekOptions : {}), ...glmSettings }, { signal });
    const fragments = new Map(); text = ''; usage = { input: null, output: null }; truncated = false;
    let finished = false, argumentCharacters = 0;
    for await (const event of stream) {
      const choice = event.choices?.[0]; responseId = event.id || responseId;
      returnedModel = event.model || returnedModel; finishReason = choice?.finish_reason || finishReason;
      text += choice?.delta?.content || '';
      if (text.length > 250000) throw Error('Model response too long');
      for (const call of choice?.delta?.tool_calls || []) {
        if (!Number.isInteger(call.index) || call.index < 0 || call.index > 8) throw Error('Invalid tool index');
        const entry = fragments.get(call.index) || { id: '', name: '', arguments: '' };
        if (call.id) entry.id = call.id;
        entry.name += call.function?.name || ''; entry.arguments += call.function?.arguments || '';
        argumentCharacters += (call.function?.arguments || '').length;
        if (argumentCharacters > 250000 || entry.name.length > 200) throw Error('Tool arguments too long');
        fragments.set(call.index, entry);
      }
      if (choice?.finish_reason === 'length') truncated = true;
      if (choice?.finish_reason) { finished = true; if (!['stop', 'tool_calls'].includes(choice.finish_reason)) truncated = true; }
      if (event.usage) { rawUsage = event.usage; usage = config.id === 'deepseek' ? deepseekUsage(event.usage) : { input: event.usage.prompt_tokens ?? null, output: event.usage.completion_tokens ?? null }; }
    }
    if (!finished) truncated = true;
    calls = [...fragments.values()];
  }
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  return { calls, text, usage, rawUsage: rawUsage ?? response?.usage ?? response?.usageMetadata ?? null, truncated, responseId: responseId || null, ...(config.id === 'deepseek' ? {requestMetadata:deepseekMetadata(config,responseId,returnedModel,finishReason)} : {}) };
}
export async function* generate(config, messages, signal, dependencies = {}) {
  const instructions = instructionsFor(config.language);
  if (config.id === 'anthropic') {
    const stream = await anthropic(config, dependencies.fetch).messages.create({ model: config.model, max_tokens: config.maxTokens, system: instructions, messages: messages.map(m => ({ role: m.role, content: m.content })), stream: true }, { signal });
    for await (const event of stream) {
      if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') yield { text: event.delta.text };
      if (event.type === 'message_start') yield { usage: { input: event.message.usage.input_tokens } };
      if (event.type === 'message_delta') {
        yield { usage: { output: event.usage.output_tokens } };
        if (event.delta.stop_reason === 'max_tokens') yield { warning: '输出达到限制，可提高输出上限后重试' };
      }
    }
  } else if (config.id === 'gemini') {
    const client = dependencies.google || gemini(config);
    const stream = await client.models.generateContentStream({ model: config.model, contents: messages.map(m => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] })), config: { systemInstruction: instructions, maxOutputTokens: config.maxTokens, abortSignal: signal } });
    for await (const event of stream) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      if (event.text) yield { text: event.text };
      if (event.usageMetadata) yield { usage: { input: event.usageMetadata.promptTokenCount ?? null, output: event.usageMetadata.candidatesTokenCount ?? null } };
    }
  } else if (config.id === 'openai') {
    const stream = await openai(config, dependencies.fetch).responses.create({ model: config.model, instructions, input: messages.map(m => ({ role: m.role, content: m.content })), max_output_tokens: config.maxTokens, store: false, stream: true }, { signal });
    for await (const event of stream) {
      if (event.type === 'response.output_text.delta') yield { text: event.delta };
      if (event.type === 'response.completed' || event.type === 'response.incomplete') {
        const u = event.response.usage;
        if (u) yield { usage: { input: u.input_tokens, output: u.output_tokens } };
        if (event.type === 'response.incomplete') yield { warning: '输出达到限制，可提高输出上限后重试' };
      }
      if (event.type === 'response.failed' || event.type === 'error') throw new Error('Upstream generation failed');
      if (event.type === 'response.refusal.delta') yield { text: event.delta };
    }
  } else {
    const glmSettings = config.id === 'glm' && /^glm-5\.3/.test(config.model) ? { reasoning_effort: 'low' } : {};
    const stream = await openai(config, dependencies.fetch).chat.completions.create({ model: config.model, messages: [{ role: 'system', content: instructions }, ...messages.map(m => ({ role: m.role, content: m.content }))], max_tokens: config.maxTokens, stream: true, ...(config.id === 'deepseek' ? deepseekOptions : {}), ...glmSettings }, { signal });
    let finished=false,responseId,returnedModel,finishReason,characters=0;
    for await (const event of stream) {
      signal.throwIfAborted();
      const choice = event.choices?.[0];
      responseId=event.id||responseId;returnedModel=event.model||returnedModel;
      if (choice?.delta?.content) { characters+=choice.delta.content.length;if(characters>1000000)throw Error('Model response too long');yield { text: choice.delta.content }; }
      if(choice?.finish_reason){finished=true;finishReason=choice.finish_reason;}
      if (choice?.finish_reason === 'length') yield { warning: '输出达到限制，可提高输出上限后重试' };
      if (event.usage) yield { usage: config.id==='deepseek'?deepseekUsage(event.usage):{ input: event.usage.prompt_tokens, output: event.usage.completion_tokens }, rawUsage:event.usage };
    }
    if(config.id==='deepseek'){
      if(!finished)throw Error('DeepSeek stream ended without completion');
      if(!['stop','length'].includes(finishReason))throw Error('DeepSeek response did not complete normally');
      yield {requestMetadata:deepseekMetadata(config,responseId,returnedModel,finishReason)};
    }
  }
}
export async function listModels(config, signal) {
  if (config.id === 'glm') { const spec = catalog.find(p => p.id === 'glm'); return { models: spec.regions.find(r => r.id === config.region)?.models || spec.models, source: 'preset', verified: false }; }
  let models;
  if (config.id === 'gemini') {
    models = [];
    const pager = await gemini(config).models.list({ config: { pageSize: 100, abortSignal: signal } });
    for await (const model of pager) if (model.supportedActions?.some(a => /generateContent/i.test(a))) models.push(model.name.replace(/^models\//, ''));
  } else {
    const client = config.id === 'anthropic' ? anthropic(config) : openai(config);
    const page = await client.models.list({}, { signal });
    models = [];
    for await (const model of page) { models.push(model.id); if (models.length >= 1000) break; }
    if (config.id === 'openai') models = models.filter(m => /^(gpt-|o[134])/.test(m) && !/audio|realtime|image|transcribe|tts|search|instruct|codex|embedding|moderation/i.test(m));
  }
  return { models: [...new Set(models)].sort(), source: 'api', verified: true };
}
export async function testConnection(config, signal) {
  // A deliberately small, user-triggered real request verifies the selected model, not just authentication.
  let received = false;
  for await (const chunk of generate({ ...config, maxTokens: Math.min(config.maxTokens, 1024) }, [{ role: 'user', content: 'Reply only: OK' }], signal)) if (chunk.text) received = true;
  if (!received) throw new Error('Empty provider response');
  return { ok: true, model: config.model };
}
