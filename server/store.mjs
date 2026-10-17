import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { atomicJson, loadWorkspace, restoreSnapshot, StorageError } from './persistence.mjs';
import catalog from '../shared/providers.json' with { type: 'json' };
import { methodPresets } from '../shared/methods.mjs';
export { catalog };
export class Store {
  constructor(directory, vault) {
    this.directory = directory; this.vault = vault;
    fs.mkdirSync(directory, { recursive: true });
    this.file = path.join(directory, 'workspace.json');
    this.backup = this.file + '.bak';
    this.recovery = null;
    const freshWorkspace = () => ({ version: 1, preferences: { theme: 'light', provider: 'openai', sidebarCollapsed: false }, providers: {}, conversations: [] });
    Object.assign(this, loadWorkspace(this.file, freshWorkspace));
    this.storageError = null;
    this.committed = structuredClone(this.data);
    // Add preferences to existing workspaces without moving records or touching keys.
    this.data.preferences ||= {}; this.data.providers ||= {};
    this.data.preferences.language = this.data.preferences.language === 'en' ? 'en' : 'zh-CN';
    if(!Object.hasOwn(methodPresets,this.data.preferences.methodPreset))this.data.preferences.methodPreset='full';
    if(typeof this.data.preferences.protocolCorrection!=='boolean')this.data.preferences.protocolCorrection=true;
    if(!['system','calibri','times','arial','georgia','verdana'].includes(this.data.preferences.readingFont))this.data.preferences.readingFont='system';
    if (!Number.isInteger(this.data.preferences.fontSize) || this.data.preferences.fontSize < 14 || this.data.preferences.fontSize > 24) this.data.preferences.fontSize = 18;
    if (!['solve', 'chat'].includes(this.data.preferences.chatMode)) this.data.preferences.chatMode = 'solve';
    if (!['highs', 'gurobi'].includes(this.data.preferences.chatEngine)) this.data.preferences.chatEngine = 'highs';
    for (const provider of catalog) this.data.providers[provider.id] ??= { region: provider.regions[0].id, model: provider.defaultModel, baseURL: '', maxTokens: 4096, models: [] };
    for (const settings of Object.values(this.data.providers)) { settings.modelingTokens ??= 4096; settings.explanationTokens ??= 768; }
    for (const conversation of this.data.conversations) { if (!Array.isArray(conversation.messages)) conversation.messages = []; if (typeof conversation.updatedAt !== 'string') conversation.updatedAt = new Date().toISOString(); }
    for (const conversation of this.data.conversations) for (const message of conversation.messages) if (message.status === 'streaming') {
      message.status = 'interrupted'; message.error = '上次生成已中断';
      if (message.automation?.interpretation === 'running') { message.automation.interpretation = 'stopped'; message.automation.stage = message.automation.result?.invoked ? 'complete' : 'stopped'; }
      else if (message.automation && ['modeling', 'checking', 'solving', 'interpreting', 'reviewing', 'repairing', 'protocol_repair', 'queued'].includes(message.automation.stage)) message.automation.stage = 'stopped';
    }
    this.save();
  }
  save() {
    this.assertWritable();
    try {
      // Back up the last committed snapshot before replacing the primary file.
      atomicJson(this.backup, this.committed);
      atomicJson(this.file, this.data);
      this.committed = structuredClone(this.data);
    } catch (error) {
      restoreSnapshot(this.data, this.committed);
      this.storageError = error instanceof StorageError ? error : new StorageError(error);
      throw this.storageError;
    }
  }
  assertWritable() { if (this.storageError) { restoreSnapshot(this.data, this.committed); throw this.storageError; } }

  publicState() {
    const providers = Object.fromEntries(Object.entries(this.data.providers).map(([id, { encryptedKey, ...settings }]) => [id, { ...settings, hasKey: !!encryptedKey }]));
    return { version: 1, preferences: this.data.preferences, providers, recovery: this.recovery, storageError: this.storageError?.message || null, conversations: this.data.conversations.toSorted((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || '')), catalog };
  }
  async configure(id, values) {
    this.assertWritable();
    const provider = catalog.find(p => p.id === id);
    if (!provider) throw new Error('未知服务商');
    if (!provider.regions.some(r => r.id === values.region)) throw new Error('请选择有效地区');
    const model = String(values.model || provider.defaultModel).trim();
    if (!model || model.length > 150 || /[\r\n]/.test(model)) throw new Error('模型 ID 无效');
    let baseURL = String(values.baseURL || '').trim().replace(/\/+$/, '');
    if (baseURL) {
      const url = new URL(baseURL);
      if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new Error('自定义地址需为不带凭据或查询参数的 HTTPS 地址');
    }
    const maxTokens = Number(values.maxTokens ?? 4096);
    if (!Number.isInteger(maxTokens) || maxTokens < 256 || maxTokens > 327680) throw new Error('输出上限应为 256–327680');
    const modelingTokens = Number(values.modelingTokens ?? this.data.providers[id].modelingTokens ?? 4096);
    const explanationTokens = Number(values.explanationTokens ?? this.data.providers[id].explanationTokens ?? 768);
    for (const value of [modelingTokens, explanationTokens]) if (!Number.isInteger(value) || value < 256 || value > 327680) throw new Error('输出上限应为 256–327680');
    let encryptedKey = this.data.providers[id].encryptedKey;
    if (values.removeKey) encryptedKey = undefined;
    else if (typeof values.apiKey === 'string' && values.apiKey.trim()) {
      const key = values.apiKey.trim();
      if (key.length > 4096 || /[\r\n\s]/.test(key)) throw new Error('密钥格式无效');
      encryptedKey = await this.vault.protect(key);
    }
    const old = this.data.providers[id];
    this.data.providers[id] = { ...old, region: values.region, model, baseURL, maxTokens, modelingTokens, explanationTokens, encryptedKey, models: old.region === values.region && old.baseURL === baseURL ? old.models : [] };
    this.save();
    return this.publicState();
  }
  async credentials(id) {
    const spec = catalog.find(p => p.id === id), settings = this.data.providers[id];
    if (!spec || !settings?.encryptedKey) throw new Error('请先在设置中填写 API 密钥');
    return { ...settings, id, apiKey: await this.vault.unprotect(settings.encryptedKey), baseURL: settings.baseURL || spec.regions.find(r => r.id === settings.region).baseURL };
  }
  create() {
    this.assertWritable();
    const now = new Date().toISOString();
    const conversation = { id: crypto.randomUUID(), title: this.data.preferences.language === 'en' ? 'New chat' : '新对话', autoTitle: true, createdAt: now, updatedAt: now, messages: [] };
    this.data.conversations.push(conversation); this.save(); return conversation;
  }
  get(id) { return this.data.conversations.find(c => c.id === id); }
  touch(conversation) { conversation.updatedAt = new Date().toISOString(); this.save(); }
  record(event) { try { fs.appendFileSync(path.join(this.directory, 'requests.ndjson'), JSON.stringify({ at: new Date().toISOString(), ...event }) + '\n', { mode: 0o600 }); } catch (error) { this.storageError = new StorageError(error); throw this.storageError; } }
}
