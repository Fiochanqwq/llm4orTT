import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { extractFile, listPackage } from '@electron/asar';
const version = JSON.parse(fs.readFileSync('package.json', 'utf8')).version;
const destination = `release/${version}/win-unpacked`, archive = destination + '/resources/app.asar';
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function list(directory, prefix = '') { return fs.readdirSync(directory, { withFileTypes: true }).flatMap(item => item.isDirectory() ? list(path.join(directory, item.name), prefix + item.name + '/') : [prefix + item.name]); }
const matches = [];
for (const file of list('build/stage').filter(f => f !== 'package.json')) {
  const source = digest(fs.readFileSync('build/stage/' + file));
  const external = ['README.txt', 'THIRD_PARTY_NOTICES.txt'].includes(file);
  const packed = digest(external ? fs.readFileSync(destination + '/' + file) : extractFile(archive, path.normalize(file)));
  assert.equal(packed, source, 'Packaged file differs: ' + file); matches.push({ file, sha256: source });
}
const entries = listPackage(archive);
assert(!entries.some(f => /^[/\\](node_modules|qa|\.local|test)([/\\]|$)/.test(f)), 'Development packages/data must not be distributed.');
const runtimeMatches = [], runtimeOmitted = [];
for (const root of ['runtime/python', 'solver']) for (const file of list(root)) {
  const relative = root + '/' + file;
  const excluded = root === 'runtime/python' && file.split('/').some(p => ['__pycache__', 'tests', 'test', 'examples', 'benchmarks'].includes(p));
  if (excluded) { assert(!fs.existsSync(destination + '/resources/' + relative)); runtimeOmitted.push(relative); continue; }
  const sha256 = digest(fs.readFileSync(relative));
  assert.equal(digest(fs.readFileSync(destination + '/resources/' + relative)), sha256, relative);
  runtimeMatches.push({ file: relative, bytes: fs.statSync(relative).size, sha256 });
}
assert(fs.existsSync(destination + '/resources/app.asar.unpacked/server/secrets.ps1'));
assert.deepEqual(fs.readdirSync(destination + '/locales').sort(), ['en-US.pak', 'zh-CN.pak']);
for (const file of ['Browser.cmd', 'README.txt', 'THIRD_PARTY_NOTICES.txt', 'LICENSE.electron.txt', 'LICENSES.chromium.html']) assert(fs.existsSync(destination + '/' + file), file);
const artifacts = [destination + '/llm4orOvO.exe', `release/${version}/llm4orOvO Setup ${version}.exe`].map(file => ({ file, bytes: fs.statSync(file).size, sha256: digest(fs.readFileSync(file)) }));
const unpackedBytes = list(destination).reduce((sum, file) => sum + fs.statSync(destination + '/' + file).size, 0);
const directory = path.resolve('qa', 'artifact-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
const report = { status: 'passed', kind: 'package_integrity_not_provider_validation', date: new Date().toISOString(), directory, matches, runtimeMatches, runtimeOmitted, unpackedBytes, artifacts };
fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ status: report.status, directory, matchedFiles: matches.length, runtimeFiles: runtimeMatches.length, omittedFiles: runtimeOmitted.length, unpackedBytes, artifacts }));
