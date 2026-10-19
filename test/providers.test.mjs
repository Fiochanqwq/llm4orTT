import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
const { generate, readableError, listModels } = await import(process.env.FYPPPPP_TEST_BUNDLE === '1' ? '../build/stage/server/providers.mjs' : '../server/providers.mjs');
function sse(events) { return new Response(events.map(e => (e.type ? 'event: ' + e.type + '\n' : '') + 'data: ' + (typeof e === 'string' ? e : JSON.stringify(e)) + '\n\n').join(''), { headers: { 'content-type': 'text/event-stream' } }); }
const base = { apiKey: 'qa-fake-key', baseURL: 'https://test.invalid', model: 'qa-model', maxTokens: 1024 };
const messages = [{ role: 'user', content: 'test' }];
for (const id of ['openai', 'anthropic', 'glm', 'deepseek', 'qwen']) test(id + ': official SDK serializes request and application consumes stream', async () => {
  let request;
  const fetch = async (url, options) => {
    request = { url: String(url), body: JSON.parse(options.body) };
    if (id === 'openai') return sse([{ type: 'response.output_text.delta', delta: 'OK' }, { type: 'response.completed', response: { usage: { input_tokens: 1, output_tokens: 1 } } }]);
    if (id === 'anthropic') return sse([{ type: 'message_start', message: { usage: { input_tokens: 1 } } }, { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'OK' } }, { type: 'message_delta', delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 1 } }, { type: 'message_stop' }]);
    return sse([{ choices: [{ delta: { content: 'OK' }, finish_reason: null }] }, { choices: [{ delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: 1, completion_tokens: 1 } }, '[DONE]']);
  };
  const chunks = []; for await (const chunk of generate({ ...base, id }, messages, new AbortController().signal, { fetch })) chunks.push(chunk);
  assert.equal(chunks.map(c => c.text || '').join(''), 'OK'); assert.equal(request.body.model, 'qa-model'); assert.equal(request.body.stream, true);
  assert.ok(!('temperature' in request.body));
  if (id === 'openai') { assert.match(request.url, /responses/); assert.equal(request.body.store, false); }
  else if (id === 'anthropic') assert.match(request.url, /messages/);
  else assert.match(request.url, /chat\/completions/);
});
test('Gemini official SDK uses generateContentStream and preserves text/usage', async t => {
  let payload;
  const server = http.createServer(async (req, res) => { let data = ''; for await (const chunk of req) data += chunk; payload = JSON.parse(data); res.writeHead(200, { 'content-type': 'text/event-stream' }); res.end('data: ' + JSON.stringify({ candidates: [{ content: { role: 'model', parts: [{ text: 'OK' }] }, finishReason: 'STOP' }], usageMetadata: { promptTokenCount: 1, candidatesTokenCount: 1 } }) + '\n\n'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); t.after(() => new Promise(resolve => server.close(resolve)));
  const chunks = [];
  for await (const chunk of generate({ ...base, id: 'gemini', baseURL: 'http://127.0.0.1:' + server.address().port }, messages, new AbortController().signal)) chunks.push(chunk);
  assert.equal(chunks.map(c => c.text || '').join(''), 'OK'); assert.equal(payload.contents[0].role, 'user'); assert.equal(payload.generationConfig.maxOutputTokens, 1024);
});
test('errors redact provider internals and map common failures', () => {
  for (const status of [400, 401, 403, 404, 429, 500]) { const value = readableError({ status, message: 'secret sk-example' }); assert.ok(!value.includes('sk-example')); assert.notEqual(value, '连接失败，请检查网络、接口地址与模型配置'); }
});
test('ordinary chat uses general conversation instructions through the SDK', async () => {
  let instructions;
  const fetch = async (_url, options) => { instructions = JSON.parse(options.body).instructions; return sse([{ type: 'response.output_text.delta', delta: '你好' }, { type: 'response.completed', response: {} }]); };
  for await (const _chunk of generate({ ...base, id: 'openai', purpose: 'chat' }, messages, new AbortController().signal, { fetch })) { /* Consume the official SDK stream. */ }
  assert.match(instructions, /通用对话助手/); assert.ok(!instructions.includes('你是上下文逆优化的结构假设生成器'));
});

const historicalModels = ['deepseek-chat', 'deepseek-coder', 'deepseek-reasoner',
  'deepseek-ai/DeepSeek-V2-Chat', 'deepseek-ai/DeepSeek-Coder-V2-Instruct', 'deepseek-ai/DeepSeek-V2.5-1210',
  'deepseek-ai/DeepSeek-V3', 'deepseek-ai/DeepSeek-V3-0324', 'deepseek-ai/DeepSeek-R1',
  'deepseek-ai/DeepSeek-R1-0528', 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B',
  'deepseek-ai/DeepSeek-V3.1-Terminus', 'deepseek-ai/DeepSeek-V3.2-Exp', 'deepseek-ai/DeepSeek-V3.2-Speciale'];
const modernModels = ['deepseek-flash', 'deepseek-v4-pro', 'deepseek-v4-flash',
  'deepseek-v4-flash-vision-exp', 'DeepSeek-V4.1-Flash-1017'];
const unknownModels = ['vendor/future-snapshot-unknown', 'vendor/DeepSeek-V5-Pro'];
for (const model of [...historicalModels, ...modernModels, ...unknownModels]) {
  test('DeepSeek preserves ID and uses compatible request fields: ' + model, async () => {
    let request;
    const fetch = async (url, options) => {
      request = { url: String(url), ...JSON.parse(options.body) };
      return sse([
        { id: 'response-fixture', model: 'actual-backend', choices: [{ delta: { reasoning_content: 'private reasoning' } }] },
        { choices: [{ delta: { content: 'final answer' } }] },
        { choices: [{ delta: {}, finish_reason: 'stop' }] },
        { choices: [], usage: { prompt_tokens: 13, completion_tokens: 17 } }, '[DONE]'
      ]);
    };
    const chunks = [];
    const history = [{ role: 'user', content: 'first' }, { role: 'assistant', content: 'previous' }, { role: 'user', content: 'next' }];
    for await (const chunk of generate({ ...base, id: 'deepseek', model, maxTokens: 100000 }, history, new AbortController().signal, { fetch })) chunks.push(chunk);
    assert.equal(request.model, model);
    assert.deepEqual(request.messages.slice(1), history);
    assert.equal(chunks.map(c => c.text || '').join(''), 'final answer');
    assert.deepEqual(chunks.find(c => c.usage).usage, { input: 13, output: 17 });
    const metadata = chunks.find(c => c.requestMetadata).requestMetadata;
    assert.equal(metadata.requestedModel, model); assert.equal(metadata.returnedModel, 'actual-backend');
    assert.equal(metadata.responseId, 'response-fixture'); assert.equal(metadata.maxOutputTokens, request.max_tokens);
    assert.equal(metadata.requestedMaxOutputTokens, 100000);
    if (modernModels.includes(model)) {
      assert.deepEqual(request.thinking, { type: 'enabled' }); assert.equal(request.reasoning_effort, 'high');
      assert.equal(request.stream_options.include_usage, true); assert.equal(request.max_tokens, 100000);
    } else {
      for (const field of ['thinking', 'reasoning_effort', 'stream_options', 'temperature']) assert.ok(!(field in request));
      const expected = /reasoner|r1/i.test(model) ? 65536 : unknownModels.includes(model) ? 100000 : 4096;
      assert.equal(request.max_tokens, expected);
    }
  });
}

test('DeepSeek length finish warns; missing or abnormal finish fails', async () => {
  for (const reason of ['length', null, 'content_filter', 'tool_calls']) {
    const chunks = [];
    const fetch = async () => sse([{ choices: [{ delta: { content: 'partial' }, finish_reason: reason }] }, '[DONE]']);
    const consume = async () => { for await (const c of generate({ ...base, id: 'deepseek', model: 'deepseek-chat' }, messages, new AbortController().signal, { fetch })) chunks.push(c); };
    if (reason === 'length') { await consume(); assert.ok(chunks.some(c => c.warning)); }
    else { await assert.rejects(consume(), /DeepSeek/); assert.ok(!chunks.some(c => c.requestMetadata)); }
  }
});

test('DeepSeek cancellation and rejected credentials do not retry or switch models', async () => {
  let attempts = 0;
  const fetch = async () => { attempts++; return new Response(JSON.stringify({ error: { message: 'invalid key' } }), { status: 401, headers: { 'content-type': 'application/json' } }); };
  await assert.rejects(async () => { for await (const _ of generate({ ...base, id: 'deepseek' }, messages, new AbortController().signal, { fetch })) {} }, e => e.status === 401);
  assert.equal(attempts, 1);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(async () => { for await (const _ of generate({ ...base, id: 'deepseek' }, messages, controller.signal, { fetch })) {} }, /abort/i);
  assert.equal(attempts, 1);
});

test('DeepSeek discovers historical and future models from the configured endpoint', async () => {
  let url;
  const config = { ...base, id: 'deepseek', baseURL: 'https://gateway.invalid/v1' };
  const result = await listModels(config, new AbortController().signal, { fetch: async value => {
    url = String(value);
    return new Response(JSON.stringify({ object: 'list', data: ['custom/future-9', 'deepseek-chat', 'deepseek-chat', 'deepseek-flash'].map(id => ({ id, object: 'model', owned_by: 'fixture' })) }), { headers: { 'content-type': 'application/json' } });
  } });
  assert.equal(url, 'https://gateway.invalid/v1/models');
  assert.deepEqual(result, { models: ['custom/future-9', 'deepseek-chat', 'deepseek-flash'], source: 'api', verified: true });
});
