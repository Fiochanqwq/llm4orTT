// WHATWG Fetch blocked ports, cross-checked against the bundled Node 24 Undici list.
// OS-assigned ephemeral ports are not necessarily safe for browser/fetch clients.
const blockedPorts = new Set([1,7,9,11,13,15,17,19,20,21,22,23,25,37,42,43,53,69,77,79,87,95,101,102,103,104,109,110,111,113,115,117,119,123,135,137,139,143,161,179,389,427,465,512,513,514,515,526,530,531,532,540,548,554,556,563,587,601,636,989,990,993,995,1719,1720,1723,2049,3659,4045,4190,5060,5061,6000,6566,6665,6666,6667,6668,6669,6679,6697,10080]);

export async function listenLoopback(server, port) {
  if (!Number.isInteger(port) || port < 0 || port > 65535 || blockedPorts.has(port)) {
    throw Object.assign(new Error('请选择浏览器允许访问的本地 HTTP 端口。'), { code: 'INVALID_HTTP_PORT' });
  }
  for (let attempt = 0; attempt < 16; attempt++) {
    await new Promise((resolve, reject) => {
      const fail = error => { server.removeListener('error', fail); reject(error); };
      server.once('error', fail);
      try { server.listen(port, '127.0.0.1', () => { server.removeListener('error', fail); resolve(); }); }
      catch (error) { fail(error); }
    });
    if (!blockedPorts.has(server.address().port)) return;
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
  throw Object.assign(new Error('系统连续分配了浏览器禁止的端口，请指定可用的本地 HTTP 端口。'), { code: 'NO_SAFE_HTTP_PORT' });
}
