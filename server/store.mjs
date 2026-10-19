import fs from 'node:fs';
import path from 'node:path';
import { atomicJson, loadWorkspace, StorageError } from './persistence.mjs';
import catalog from '../shared/providers.json' with { type: 'json' };
export { catalog };

export class Store {
  constructor(directory, vault) {
    this.directory = directory; this.vault = vault;
    fs.mkdirSync(directory, { recursive: true });
    this.file = path.join(directory, 'inverse-workspace.json'); this.backup = this.file + '.bak';
    // Import only model settings. Legacy history stays untouched pending approved cleanup.
    const seed = () => {
      for (const name of ['workspace.json', 'workspace.json.bak']) {
        try {
          const old = JSON.parse(fs.readFileSync(path.join(directory, name), 'utf8'));
          if (old.version === 1 && old.providers && old.preferences) return old;
        } catch { /* New workspaces have no previous settings. */ }
      }
      return { version: 1, preferences: {}, providers: {} };
    };
    const { data } = loadWorkspace(this.file, seed);
    const old = data.preferences || {};
    this.data = { version: 1, preferences: { provider: catalog.some(p => p.id === old.provider) ? old.provider : 'openai', theme: old.theme === 'graphite' ? 'graphite' : 'light', fontSize: 16 }, providers: {} };
    for (const provider of catalog) {
      const prior = data.providers[provider.id] || {};
      this.data.providers[provider.id] = { region: provider.regions.some(r => r.id === prior.region) ? prior.region : provider.regions[0].id, model: prior.model || provider.defaultModel,
        baseURL: prior.baseURL || '', maxTokens: prior.maxTokens || 8192, models: Array.isArray(prior.models) ? prior.models : [], ...(prior.encryptedKey ? { encryptedKey: prior.encryptedKey } : {}) };
    }
    this.committed = structuredClone(this.data); this.save();
  }
  assertWritable() { if (this.storageError) throw this.storageError; }
  save() {
    this.assertWritable();
    try { atomicJson(this.backup, this.committed); atomicJson(this.file, this.data); this.committed = structuredClone(this.data); }
    catch (error) { this.data = structuredClone(this.committed); this.storageError = error instanceof StorageError ? error : new StorageError(error); throw this.storageError; }
  }
  publicState() {
    return { version: 1, preferences: this.data.preferences, catalog,
      providers: Object.fromEntries(Object.entries(this.data.providers).map(([id, { encryptedKey, ...settings }]) => [id, { ...settings, hasKey: !!encryptedKey }])) };
  }
  async configure(id, values) {
    this.assertWritable();
    const spec = catalog.find(p => p.id === id);
    if (!spec || !spec.regions.some(r => r.id === values.region)) throw Error('请选择有效服务商和地区');
    const model = String(values.model || spec.defaultModel).trim();
    if (!model || model.length > 150 || /[\r\n]/.test(model)) throw Error('模型 ID 无效');
    const baseURL = String(values.baseURL || '').trim().replace(/\/+$/, '');
    if (baseURL) { const url = new URL(baseURL); if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw Error('自定义地址需为无凭据、无查询参数的 HTTPS 地址'); }
    const maxTokens = Number(values.maxTokens ?? 8192);
    if (!Number.isInteger(maxTokens) || maxTokens < 256 || maxTokens > 393216) throw Error('输出上限应为 256–393216');
    const old = this.data.providers[id]; let encryptedKey = old.encryptedKey;
    if (values.removeKey) encryptedKey = undefined;
    else if (typeof values.apiKey === 'string' && values.apiKey.trim()) {
      const key = values.apiKey.trim(); if (key.length > 4096 || /\s/.test(key)) throw Error('密钥格式无效');
      encryptedKey = await this.vault.protect(key);
    }
    this.data.providers[id] = { region: values.region, model, baseURL, maxTokens, encryptedKey, models: old.region === values.region && old.baseURL === baseURL ? old.models : [] };
    this.save(); return this.publicState();
  }
  async credentials(id) {
    const spec = catalog.find(p => p.id === id), settings = this.data.providers[id];
    if (!spec || !settings?.encryptedKey) throw Error('请先在设置中填写 API 密钥');
    return { ...settings, id, language: 'zh-CN', apiKey: await this.vault.unprotect(settings.encryptedKey), baseURL: settings.baseURL || spec.regions.find(r => r.id === settings.region).baseURL };
  }
}
