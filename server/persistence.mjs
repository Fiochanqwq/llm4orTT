import fs from 'node:fs';
import crypto from 'node:crypto';

export class StorageError extends Error {
  constructor(cause) { super('本地记录暂时无法保存，已暂停新任务。请检查磁盘空间或文件权限，恢复后重新启动。', { cause }); this.code = 'STORAGE_UNAVAILABLE'; }
}
export function atomicJson(file, value) {
  const temp = file + '.' + crypto.randomUUID() + '.tmp';
  try { fs.writeFileSync(temp, JSON.stringify(value, null, 2), { mode: 0o600 }); fs.renameSync(temp, file); }
  catch (error) { throw new StorageError(error); }
  finally { try { fs.unlinkSync(temp); } catch {} }
}
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export function validWorkspace(value) {
  return object(value) && value.version === 1 && object(value.preferences) && object(value.providers)
    && Object.values(value.providers).every(object) && Array.isArray(value.conversations)
    && value.conversations.every(c => object(c) && typeof c.id === 'string' && typeof c.title === 'string'
      && Array.isArray(c.messages) && c.messages.every(m => object(m) && typeof m.role === 'string' && typeof m.content === 'string'
        && (m.automation == null || (object(m.automation) && (m.automation.task == null || object(m.automation.task))))));
}
export function readValidated(file, valid) {
  try { const value = JSON.parse(fs.readFileSync(file, 'utf8')); return valid(value) ? value : null; }
  catch (error) { if (error instanceof SyntaxError || error.code === 'ENOENT') return null; throw new StorageError(error); }
}
export function loadWorkspace(file, fresh) {
  const backup = file + '.bak';
  const current = readValidated(file, validWorkspace);
  if (current) return { data: current, recovery: null };
  const exists = fs.existsSync(file), saved = readValidated(backup, validWorkspace);
  const badBackup = !saved && fs.existsSync(backup);
  let quarantined = null;
  if (exists) {
    quarantined = file + '.corrupt-' + crypto.randomUUID();
    // Do not replace the source if preserving it fails.
    try { fs.renameSync(file, quarantined); } catch (error) { throw new StorageError(error); }
  }
  let backupCorrupted = null;
  if (badBackup) {
    backupCorrupted = backup + '.corrupt-' + crypto.randomUUID();
    try { fs.renameSync(backup, backupCorrupted); } catch (error) { throw new StorageError(error); }
  }
  return { data: saved || fresh(), recovery: exists || saved || badBackup ? { corrupted: quarantined, backupCorrupted, restoredFromBackup: !!saved } : null };
}
// Keep references held by in-flight conversations while restoring committed fields.
export function restoreSnapshot(target, snapshot) {
  if (Array.isArray(target) && Array.isArray(snapshot)) {
    const old = [...target];
    target.splice(0, target.length, ...snapshot.map((value, i) => {
      const prior = object(value) && value.id ? old.find(x => x?.id === value.id) : old[i];
      return compatible(prior, value) ? restoreSnapshot(prior, value) : structuredClone(value);
    }));
  } else {
    for (const key of Object.keys(target)) if (!Object.hasOwn(snapshot, key)) delete target[key];
    for (const [key, value] of Object.entries(snapshot)) target[key] = compatible(target[key], value) ? restoreSnapshot(target[key], value) : structuredClone(value);
  }
  return target;
}
function compatible(a, b) { return (Array.isArray(a) && Array.isArray(b)) || (object(a) && object(b)); }
