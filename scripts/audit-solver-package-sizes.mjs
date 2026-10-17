// Read public distribution metadata only. Does not install or execute solver packages.
import fs from 'node:fs';
import path from 'node:path';
const directory = path.resolve('qa', 'solver-package-sizes-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(directory, { recursive: true });
const packages = await Promise.all(['gurobipy', 'highspy', 'pyomo', 'PuLP', 'scipy', 'numpy', 'ply'].map(async name => {
  const source = `https://pypi.org/pypi/${name}/json`;
  const response = await fetch(source, { signal: AbortSignal.timeout(20000) });
  if (!response.ok) throw new Error(name + ': ' + response.status);
  const data = await response.json();
  const matches = data.urls.filter(file => !file.yanked && file.packagetype === 'bdist_wheel' && (/cp312-cp312-win_amd64\.whl$/.test(file.filename) || /py3-none-win_amd64\.whl$/.test(file.filename) || /py2\.py3-none-any\.whl$/.test(file.filename) || /py3-none-any\.whl$/.test(file.filename)));
  matches.sort((a, b) => Number(b.filename.includes('win_amd64')) - Number(a.filename.includes('win_amd64')));
  const file = matches[0];
  return { name: data.info.name, version: data.info.version, requiresPython: data.info.requires_python, requiresDist: data.info.requires_dist || [], source, project: data.info.project_url, wheel: file ? { filename: file.filename, bytes: file.size, url: file.url, sha256: file.digests.sha256 } : null };
}));
function totalBytes(directory) { return fs.readdirSync(directory, { withFileTypes: true }).reduce((sum, entry) => { const file = path.join(directory, entry.name); return sum + (entry.isDirectory() ? totalBytes(file) : fs.statSync(file).size); }, 0); }
const installerBytes = fs.statSync('release/0.2.0/llm4orOvO Setup 0.2.0.exe').size;
const report = { checkedAt: new Date().toISOString(), kind: 'distribution_metadata_not_solver_benchmark', target: 'CPython 3.12 Windows x86-64 (size comparison target, not a runtime deployment decision)', baseline: { installerBytes, unpackedBytes: totalBytes('release/0.2.0/win-unpacked') }, packages, limitation: 'Wheel sizes are compressed downloads. They are not final installer increments or installed sizes. Python runtime and transitive dependencies must be accounted for separately.' };
fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ directory, baseline: report.baseline, packages: packages.map(item => ({ name: item.name, version: item.version, filename: item.wheel?.filename, bytes: item.wheel?.bytes, requiresDist: item.requiresDist })) }));
