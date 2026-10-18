import { parseSolverResponse } from './solver-response.mjs';
import { numericalCheck } from '../shared/result-contract.mjs';
import fs from 'node:fs';
import { atomicJson, StorageError } from './persistence.mjs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { validateModel, pyomoSource } from '../shared/solver-model.mjs';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const resourceRoot = appRoot.endsWith('app.asar') ? path.dirname(appRoot) : appRoot;
const bundledPython = path.join(resourceRoot, process.platform === 'win32' ? 'runtime/python/python.exe' : 'runtime/python/bin/python');
const worker = path.join(resourceRoot, 'solver/worker.py');
const terminal = new Set(['optimal', 'infeasible', 'unbounded', 'infeasible_or_unbounded', 'time_limit', 'unknown', 'error', 'rejected', 'unavailable', 'stopped', 'interrupted', 'output_limit']);


export class SolverService {
  constructor(directory) {
    this.directory = path.join(directory, 'solver'); fs.mkdirSync(this.directory, { recursive: true });
    this.configPath = path.join(this.directory, 'settings.json');
    this.config = { gurobiPython: '' };
    try { const saved = JSON.parse(fs.readFileSync(this.configPath, 'utf8')); if (saved && typeof saved.gurobiPython === 'string') this.config = { gurobiPython: saved.gurobiPython }; } catch { }
    this.jobs = new Map(); this.active = null; this.skipped = [];
    for (const file of fs.readdirSync(this.directory).filter(f => /^[a-f0-9-]+\.json$/.test(f))) {
      // A single truncated record must not stop the application from starting.
      let record = null;
      try { record = JSON.parse(fs.readFileSync(path.join(this.directory, file), 'utf8')); } catch { record = null; }
      if (!record || typeof record.id !== 'string' || record.id + '.json' !== file || typeof record.createdAt !== 'string' || !Number.isFinite(Date.parse(record.createdAt)) || (record.status !== 'running' && !terminal.has(record.status))) { this.skipped.push(file); continue; }
      if (record.status === 'running') { record.status = 'interrupted'; record.completedAt = new Date().toISOString(); try { this.save(record); } catch { } }
      this.jobs.set(record.id, record);
    }
  }
  save(record) {
    if(this.storageError)throw this.storageError;
    try {
      atomicJson(path.join(this.directory, record.id + '.json'), record);
      fs.appendFileSync(path.join(this.directory, 'events.ndjson'), JSON.stringify({ id: record.id, status: record.status, at: new Date().toISOString() }) + '\n');
    } catch(error) { this.storageError=error instanceof StorageError?error:new StorageError(error);this.onStorageError?.(this.storageError);throw this.storageError; }
  }
  saveCompletion(record) { try { this.save(record); } catch(error) { record.persistenceError=error.message; } }

  info() { return { engines: { highs: { available: fs.existsSync(bundledPython) && fs.existsSync(worker) }, gurobi: { available: !!this.config.gurobiPython && fs.existsSync(this.config.gurobiPython) } }, gurobiPython: this.config.gurobiPython, activeId: this.active?.id || null, skippedRecords: (this.skipped || []).length, storageError: this.storageError?.message || null }; }
  configure(value) {
    if(this.storageError)throw this.storageError;
    if (this.active) throw Error('请先停止求解');
    if (typeof value.gurobiPython !== 'string') throw Error('请选择 Python 路径');
    const file = value.gurobiPython.trim();
    if (file && (!path.isAbsolute(file) || !/^python(?:3(?:\.\d+)?)?(?:\.exe)?$/i.test(path.basename(file)) || !fs.existsSync(file) || !fs.statSync(file).isFile())) throw Error('请选择有效的 Python 解释器绝对路径');
    try{atomicJson(this.configPath,{gurobiPython:file});}catch(error){this.storageError=error;this.onStorageError?.(error);throw error;}this.config = { gurobiPython: file }; return this.info();
  }
  list() { return [...this.jobs.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, 30).map(({ id, createdAt, status, engine, name, objective, durationMs }) => ({ id, createdAt, status, engine, name, objective, durationMs })); }
  get(id) { return this.jobs.get(id); }
  start(input) {
    if(this.storageError)throw this.storageError;
    if (this.active) throw Error('当前已有求解任务');
    const record = { id: crypto.randomUUID(), createdAt: new Date().toISOString(), status: 'running', name: typeof input.model?.name === 'string' ? input.model.name.slice(0, 100) : '', engine: input.engine, seconds: input.seconds, input, log: '', provenance: { source: 'local_service', solverInvoked: false, workerStarted: false } };
    this.jobs.set(record.id, record);
    try {
      record.model = validateModel(input.model);
      record.modelHash = crypto.createHash('sha256').update(JSON.stringify(record.model)).digest('hex');
      if (input.problem !== undefined && (typeof input.problem !== 'string' || input.problem.length > 12000)) throw Error('Invalid problem text');
      record.problem = input.problem || '';
      if (!['highs', 'gurobi'].includes(input.engine)) throw Error('Unsupported solver');
      if (!Number.isInteger(input.seconds) || input.seconds < 1 || input.seconds > 120) throw Error('Time limit must be 1–120 seconds');
      record.source = pyomoSource(record.model, input.engine, input.seconds);
    } catch (error) { record.status = 'rejected'; record.error = error.message; this.save(record); return record; }
    const python = input.engine === 'highs' ? bundledPython : this.config.gurobiPython;
    if (!python || !fs.existsSync(python)) { record.status = 'unavailable'; record.error = input.engine === 'gurobi' ? 'Configure a Python environment with Pyomo, gurobipy and a valid Gurobi license.' : 'Bundled solver runtime is missing.'; this.save(record); return record; }
    this.save(record);
    const started = Date.now(), env = {};
    for (const key of ['SystemRoot', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'LOCALAPPDATA', 'APPDATA', 'GRB_LICENSE_FILE']) if (process.env[key]) env[key] = process.env[key];
    env.PATH = [path.dirname(python), path.join(path.dirname(python), 'Library/bin'), path.join(process.env.SystemRoot || 'C:/Windows', 'System32')].join(path.delimiter);
    // Bound numerical-library allocation before Python imports NumPy/Pyomo.
    // The solver worker already uses one thread; BLAS otherwise sizes its own pool.
    Object.assign(env,{OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1',MKL_NUM_THREADS:'1'});
    record.provenance.numericalLibraryThreads=1;
    let child;
    try { child = spawn(python, ['-I', '-X', 'utf8', '-u', '-B', worker], { cwd: this.directory, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] }); }
    catch (error) {
      // A blocked interpreter throws synchronously here rather than raising a child 'error' event,
      // which used to leave the record stuck at 'running' with no error and no way to stop it.
      record.status = 'unavailable'; record.error = '求解器进程无法启动（' + (error.code || error.message) + '）。请检查安全软件或组策略是否阻止了本地程序运行。';
      record.completedAt = new Date().toISOString(); this.save(record); return record;
    }
    this.active = { id: record.id, child };
    child.once('spawn', () => { record.provenance.workerStarted = true; record.provenance.startedAt = new Date().toISOString(); });
    let reason, output = '', finished = false;
    const timer = setTimeout(() => { reason = 'time_limit'; child.kill(); }, (input.seconds + 15) * 1000);
    const finish = error => {
      if (finished) return; finished = true; clearTimeout(timer); this.active = null;
      const marker = output.lastIndexOf('LLM4OR_RESULT=');
      if (marker >= 0) {
        try { const result = parseSolverResponse(output.slice(marker + 14).split(/\r?\n/)[0], record.model); Object.assign(record, result); } catch { record.status = 'error'; record.error = 'Invalid solver response.'; }
        record.log = output.slice(0, marker).replace(/^LLM4OR_SOLVER_INVOKED=.*\r?\n/gm, '').trim();
      } else { record.status = 'error'; record.log = output.trim(); record.error = error?.message || 'Solver exited without a result.'; }
      if (reason) { record.status = reason; record.values = null; record.objective = null; record.error = reason==='error'?'Solver process exited abnormally.':null; }
      if (!terminal.has(record.status)) record.status = 'error';
      record.check = numericalCheck(record.model, record.values);
      record.durationMs = Date.now() - started; record.completedAt = new Date().toISOString(); this.saveCompletion(record);
    };
    const collect = chunk => { output += chunk.toString('utf8'); if (output.includes('LLM4OR_SOLVER_INVOKED=' + input.engine + '\n') || output.includes('LLM4OR_SOLVER_INVOKED=' + input.engine + '\r\n')) record.provenance.solverInvoked = true; if (output.length > 2_000_000) { output = output.slice(0, 2_000_000); reason = 'output_limit'; child.kill(); } record.log = output.slice(-32000); };
    child.stdout.on('data', collect); child.stderr.on('data', collect);
    child.on('error', finish); child.on('close', (code, signal) => { record.provenance.exitCode=code;record.provenance.exitSignal=signal;if(code!==0&&!reason){reason='error';}finish(); }); child.stdin.on('error', () => {});
    try { child.stdin.end(JSON.stringify({ model: record.model, engine: input.engine, seconds: input.seconds })); } catch { }
    this.active.stop = () => { reason = 'stopped'; child.kill(); };
    return record;
  }
  stop(id) { if (this.active?.id === id) this.active.stop(); return this.get(id); }
  close() {
    if (!this.active) return;
    const record = this.get(this.active.id);
    this.active.stop();
    // Persist before Electron exits; child close callbacks are not guaranteed at shutdown.
    if (record) { record.status = 'stopped'; record.completedAt = new Date().toISOString(); this.saveCompletion(record); }
  }
}
