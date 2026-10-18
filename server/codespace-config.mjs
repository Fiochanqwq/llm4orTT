import path from 'node:path';
import { fileURLToPath } from 'node:url';
export const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export function codespaceConfig(env = process.env) {
  if (env.CODESPACES !== 'true' || !/^[a-z0-9-]+$/.test(env.CODESPACE_NAME || '') || !/^[a-z0-9.-]+$/.test(env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN || '')) {
    throw Error('请在 GitHub Codespaces 中运行此入口。');
  }
  return { directory: path.join(appRoot, '.local/codespace-workspace'), port: 43127,
    externalOrigin: `https://${env.CODESPACE_NAME}-43127.${env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}` };
}
