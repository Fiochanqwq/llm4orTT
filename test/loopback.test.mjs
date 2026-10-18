import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { listenLoopback } from '../server/listen-loopback.mjs';

class Server extends EventEmitter {
  constructor(ports) { super(); this.ports=ports; this.binds=0; this.closes=0; }
  listen(port,host,callback) { assert.equal(host,'127.0.0.1');this.bound=this.ports[Math.min(this.binds++,this.ports.length-1)];queueMicrotask(callback); }
  address() { return {port:this.bound}; }
  close(callback) { this.closes++;this.bound=null;queueMicrotask(callback); }
}
test('ephemeral HTTP binding retries Fetch-blocked ports before returning its origin',async()=>{
  const server=new Server([6000,6667,49152]);
  await listenLoopback(server,0);
  assert.equal(server.address().port,49152);assert.equal(server.binds,3);assert.equal(server.closes,2);
  assert.equal(server.listenerCount('error'),0);
});
test('explicit unsafe ports are rejected and a safe explicit port is retained',async()=>{
  for(const port of [6000,10080,-1,65536,1.5])await assert.rejects(listenLoopback(new Server([port]),port),{code:'INVALID_HTTP_PORT'});
  const server=new Server([43127]);await listenLoopback(server,43127);assert.equal(server.closes,0);
});
test('binding failures propagate and blocked ephemeral retries are bounded',async()=>{
  const server=new Server([6000]);await assert.rejects(listenLoopback(server,0),{code:'NO_SAFE_HTTP_PORT'});assert.equal(server.closes,16);
  const failing=new Server([]);failing.listen=function(){queueMicrotask(()=>this.emit('error',Object.assign(Error('busy'),{code:'EADDRINUSE'})));};
  await assert.rejects(listenLoopback(failing,43127),{code:'EADDRINUSE'});assert.equal(failing.listenerCount('error'),0);
});
