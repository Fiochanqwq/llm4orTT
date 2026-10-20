import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().filter(k => value[k] !== undefined).map(k => [k, stable(value[k])]));
  return value;
}
export function proposalKey(prompt, config) {
  // Credentials never enter a cache key, payload or log.
  const identity = { version: 'inverse-economy-v1', prompt, provider: config.id, model: config.model,
    endpoint: config.baseURL || '', maxTokens: config.maxTokens, economy: config.economy === true };
  return crypto.createHash('sha256').update(JSON.stringify(stable(identity))).digest('hex');
}
export function proposalCache(directory) {
  const filename = key => {
    if (!/^[a-f0-9]{64}$/.test(key)) throw Error('Invalid cache key');
    return path.join(directory, key + '.json');
  };
  return {
    read(key) { try { const value = JSON.parse(fs.readFileSync(filename(key), 'utf8')); return value.version === 1 ? value.proposal : null; } catch { return null; } },
    write(key, proposal) {
      fs.mkdirSync(directory, { recursive: true });
      const file = filename(key), temp = file + '.' + crypto.randomUUID() + '.tmp';
      try { fs.writeFileSync(temp, JSON.stringify({ version: 1, proposal }), { mode: 0o600 }); fs.renameSync(temp, file); }
      finally { try { fs.unlinkSync(temp); } catch { } }
    }
  };
}
