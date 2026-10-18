import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

// Codespaces has no Windows DPAPI. Keep an authenticated encryption key in
// the private, ignored workspace; never embed it in source or browser code.
export function fileVault(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const file = path.join(directory, 'vault.key');
  let key;
  const readKey = () => {
    if (key) return key;
    try { fs.writeFileSync(file, crypto.randomBytes(32), { flag: 'wx', mode: 0o600 }); }
    catch (error) { if (error.code !== 'EEXIST') throw error; }
    key = fs.readFileSync(file);
    if (key.length !== 32) throw Error('密钥保护文件损坏，请恢复工作区备份。');
    return key;
  };
  return {
    async protect(value) {
      const iv = crypto.randomBytes(12), cipher = crypto.createCipheriv('aes-256-gcm', readKey(), iv);
      const ciphertext = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
      return 'v1:' + Buffer.concat([iv, cipher.getAuthTag(), ciphertext]).toString('base64');
    },
    async unprotect(value) {
      if (!value.startsWith('v1:')) throw Error('密钥格式不兼容，请在当前云端工作区重新填写 API Key。');
      const data = Buffer.from(value.slice(3), 'base64');
      if (data.length < 28) throw Error('密钥记录损坏。');
      const decipher = crypto.createDecipheriv('aes-256-gcm', readKey(), data.subarray(0, 12));
      decipher.setAuthTag(data.subarray(12, 28));
      return Buffer.concat([decipher.update(data.subarray(28)), decipher.final()]).toString('utf8');
    }
  };
}
