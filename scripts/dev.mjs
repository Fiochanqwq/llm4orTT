import { spawn } from 'node:child_process';
import { ensureService } from '../server/launcher.mjs';
process.env.FYPPPPP_DATA_DIR ||= new URL('../.local/', import.meta.url).pathname.replace(/^\/([A-Z]:)/i, '$1');
process.env.FYPPPPP_DEV = '1';
const service = await ensureService();
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js'], { stdio: 'inherit' });
console.log('Open http://127.0.0.1:5173/#token=' + service.token);
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, async () => { child.kill(); if (service.owned) { await service.close(); service.cleanup(); } process.exit(); });
