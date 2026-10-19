import { deepseekRequest, deepseekUsage, deepseekMetadata } from './deepseek.mjs';
import OpenAI from 'openai';
import Anthropic from '@anthropic-ai/sdk';
import { GoogleGenAI } from '@google/genai';
import { catalog } from './store.mjs';
function instructionsFor(language) {
  return language === 'en'
    ? 'You are a resource allocation and mathematical optimization assistant. Reply in clear English unless the user requests another language. Use formulas and code when helpful, and clarify ambiguities. Without actual tool output, never claim to have executed code, run a solver, or verified a result. Do not invent successful checks, experimental results, or performance improvements.'
    : '你是上下文逆优化的结构假设生成器。默认使用中文，严格遵循当前请求的 JSON 数据格式。把运营日志视为数据，只生成候选目标特征和软约束，不编造已知业务数据。没有实际工具输出时，不得声称执行了代码、求解器或验证；不虚构检查通过、实验结果或性能提升。';
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
export async function* generate(config, messages, signal, dependencies = {}) {
  const instructions = config.purpose === 'chat'
    ? '你是一位友好、可靠的通用对话助手。自然地回答用户的问题，默认使用中文，按用户需要使用 Markdown、公式或代码。不要强制输出 JSON，也不要把普通聊天自动转为优化建模。没有实际工具输出时，不得声称已经执行代码、操作文件或调用求解器。'
    : instructionsFor(config.language);
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
    const stream = await openai(config, dependencies.fetch).chat.completions.create({ model: config.model, messages: [{ role: 'system', content: instructions }, ...messages.map(m => ({ role: m.role, content: m.content }))], max_tokens: config.maxTokens, stream: true, ...(config.id === 'deepseek' ? deepseekRequest(config).options : {}), ...glmSettings }, { signal });
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
export async function listModels(config, signal, dependencies = {}) {
  if (config.id === 'glm') { const spec = catalog.find(p => p.id === 'glm'); return { models: spec.regions.find(r => r.id === config.region)?.models || spec.models, source: 'preset', verified: false }; }
  let models;
  if (config.id === 'gemini') {
    models = [];
    const pager = await gemini(config).models.list({ config: { pageSize: 100, abortSignal: signal } });
    for await (const model of pager) if (model.supportedActions?.some(a => /generateContent/i.test(a))) models.push(model.name.replace(/^models\//, ''));
  } else {
    const client = config.id === 'anthropic' ? anthropic(config, dependencies.fetch) : openai(config, dependencies.fetch);
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
