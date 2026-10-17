import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {compactResearchTool,compactReviewTool} from '../shared/compact-protocol.mjs';
const { generate, planOptimization, readableError } = await import(process.env.FYPPPPP_TEST_BUNDLE === '1' ? '../build/stage/server/providers.mjs' : '../server/providers.mjs');
function sse(events) { return new Response(events.map(e => (e.type ? 'event: ' + e.type + '\n' : '') + 'data: ' + (typeof e === 'string' ? e : JSON.stringify(e)) + '\n\n').join(''), { headers: { 'content-type': 'text/event-stream' } }); }
const base = { apiKey: 'qa-fake-key', baseURL: 'https://test.invalid', model: 'qa-model', maxTokens: 1024 };
test('compact object envelopes preserve non-strict provider schema and object responses',async()=>{
  for(const tool of [compactResearchTool,compactReviewTool]){
    let payload;const args=tool===compactReviewTool?{review_json:{status:'uncertain'}}:{contract_json:{requirements:[]}};
    const result=await planOptimization({...base,id:'openai',tool},[{role:'user',content:'offline schema check'}],new AbortController().signal,{fetch:async(_url,options)=>{
      payload=JSON.parse(options.body);return new Response(JSON.stringify({id:'offline',status:'completed',output:[{type:'function_call',call_id:'offline',name:tool.name,arguments:JSON.stringify(args)}],usage:{input_tokens:1,output_tokens:1}}),{headers:{'content-type':'application/json'}});
    }});
    assert.equal(payload.tools[0].strict,false);assert.deepEqual(JSON.parse(result.calls[0].arguments),args);
  }
});
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

const args = { action: 'clarify', model_json: '', message: 'What is the capacity?' };
for (const id of ['openai', 'anthropic', 'glm', 'deepseek', 'qwen']) test(id + ': official SDK tool request preserves arguments/usage, without exposing reasoning', async () => {
  let payload;
  const fetch = async (_url, options) => {
    payload = JSON.parse(options.body);
    if (!['openai', 'anthropic'].includes(id)) return sse([
      { id: 'qa-response', choices: [{ delta: { reasoning_content: 'private reasoning', tool_calls: [{ index: 0, id: 'qa-call', type: 'function', function: { name: 'submit_optimization', arguments: JSON.stringify(args).slice(0, 15) } }] } }] },
      { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: JSON.stringify(args).slice(15) } }] }, finish_reason: 'tool_calls' }], usage: { prompt_tokens: 2, completion_tokens: 3 } }, '[DONE]'
    ]);
    const response = id === 'openai' ? { id: 'qa-response', status: 'completed', output: [{ type: 'function_call', call_id: 'qa-call', name: 'submit_optimization', arguments: JSON.stringify(args) }], usage: { input_tokens: 2, output_tokens: 3 } }
      : id === 'anthropic' ? { id: 'qa-response', stop_reason: 'tool_use', content: [{ type: 'thinking', thinking: 'private reasoning' }, { type: 'tool_use', id: 'qa-call', name: 'submit_optimization', input: args }], usage: { input_tokens: 2, output_tokens: 3 } }
      : { id: 'qa-response', choices: [{ finish_reason: 'tool_calls', message: { role: 'assistant', content: '', reasoning_content: 'private reasoning', tool_calls: [{ id: 'qa-call', type: 'function', function: { name: 'submit_optimization', arguments: JSON.stringify(args) } }] } }], usage: { prompt_tokens: 2, completion_tokens: 3 } };
    return new Response(JSON.stringify(response), { headers: { 'content-type': 'application/json' } });
  };
  const result = await planOptimization({ ...base, id }, messages, new AbortController().signal, { fetch });
  assert.equal(result.calls.length, 1); assert.equal(result.calls[0].name, 'submit_optimization');
  assert.deepEqual(typeof result.calls[0].arguments === 'string' ? JSON.parse(result.calls[0].arguments) : result.calls[0].arguments, args);
  assert.deepEqual(result.usage, { input: 2, output: 3 }); assert.equal(result.truncated, false); assert.ok(!JSON.stringify(result).includes('private reasoning'));
  assert.equal(payload.tools.length, 1); assert.equal(!!payload.stream, !['openai', 'anthropic'].includes(id));
  if (id === 'openai') { assert.equal(payload.tool_choice.name, 'submit_optimization'); assert.equal(payload.tools[0].strict, true); }
  if (id === 'anthropic') assert.equal(payload.tool_choice.disable_parallel_tool_use, true);
});

test('Gemini official SDK serializes mandatory function declaration and parses its call', async t => {
  let payload;
  const server = http.createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk; payload = JSON.parse(body);
    res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ candidates: [{ finishReason: 'STOP', content: { role: 'model', parts: [{ thought: true, text: 'private reasoning' }, { functionCall: { name: 'submit_optimization', args } }] } }], usageMetadata: { promptTokenCount: 2, candidatesTokenCount: 3 } }));
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r)); t.after(() => new Promise(r => server.close(r)));
  const result = await planOptimization({ ...base, id: 'gemini', baseURL: 'http://127.0.0.1:' + server.address().port }, messages, new AbortController().signal);
  assert.equal(payload.toolConfig.functionCallingConfig.mode, 'ANY'); assert.equal(payload.tools[0].functionDeclarations[0].name, 'submit_optimization');
  assert.deepEqual(payload.tools[0].functionDeclarations[0].parametersJsonSchema.required, ['action', 'model_json', 'message', 'questions']);
  assert.deepEqual(result.calls[0].arguments, args); assert.deepEqual(result.usage, { input: 2, output: 3 }); assert.equal(result.text, '');
});

test('DeepSeek planner uses a fresh input transcript, without synthetic assistant reasoning', async () => {
  let payload;
  const result = await planOptimization({ ...base, id: 'deepseek' }, [{ role: 'user', content: 'budget unknown' }, { role: 'assistant', content: 'What is the budget?' }, { role: 'user', content: '320 fixed' }], new AbortController().signal, { fetch: async (_url, options) => {
    payload = JSON.parse(options.body);
    return sse([{ choices: [{ delta: { content: '{}' }, finish_reason: 'stop' }] }, '[DONE]']);
  } });
  assert.deepEqual(payload.messages.map(m => m.role), ['system', 'user']);
  assert.ok(payload.messages[1].content.includes('What is the budget?')); assert.ok(payload.messages[1].content.includes('320 fixed'));
  assert.equal(payload.tool_choice, 'auto'); assert.deepEqual(payload.thinking, {type:'enabled'}); assert.equal(payload.reasoning_effort, 'high');
  assert.equal(result.truncated, false);
});

test('compatible planning stream without a finish reason cannot be solved', async () => {
  const result = await planOptimization({ ...base, id: 'deepseek' }, messages, new AbortController().signal, { fetch: async () => sse([{ choices: [{ delta: { content: JSON.stringify(args) } }] }, '[DONE]']) });
  assert.equal(result.truncated, true);
});

test('compatible planning stream bounds untrusted tool indices', async () => {
  await assert.rejects(() => planOptimization({ ...base, id: 'deepseek' }, messages, new AbortController().signal, { fetch: async () => sse([{ choices: [{ delta: { tool_calls: [{ index: 999999, function: { name: 'bad', arguments: '{}' } }] } }] }, '[DONE]']) }), /Invalid tool index/);
});
