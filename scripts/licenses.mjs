import fs from 'node:fs';
import path from 'node:path';
const root = process.cwd(), lock = JSON.parse(fs.readFileSync('package-lock.json', 'utf8'));
const output = [`llm4orTT ${lock.version} · Third-party notices`, 'Generated from installed package versions. App code and original Saturn artwork are project-authored.', 'System Calibri and SimHei font files are not redistributed.', ''];
const summary = [];
for (const [relative, data] of Object.entries(lock.packages).sort()) {
  if (!relative || !relative.includes('node_modules/')) continue;
  const directory = path.join(root, relative); if (!fs.existsSync(directory)) continue;
  const pkg = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
  const files = fs.readdirSync(directory).filter(name => /^(license|licence|copying|notice)(\.|$)/i.test(name) && fs.statSync(path.join(directory, name)).isFile());
  summary.push({ name: pkg.name, version: pkg.version, license: pkg.license || data.license || null, development: !!data.dev, noticeFiles: files });
  output.push('\n' + '='.repeat(72), `${pkg.name} ${pkg.version}`, `License: ${typeof pkg.license === 'string' ? pkg.license : JSON.stringify(pkg.license || data.license || 'See upstream')}`);
  for (const file of files) output.push(`\n--- ${file} ---\n`, fs.readFileSync(path.join(directory, file), 'utf8'));
}
const electronLicense = path.join(root, 'node_modules/electron/dist/LICENSE');
if (fs.existsSync(electronLicense)) output.push('\nELECTRON RUNTIME LICENSE\n', fs.readFileSync(electronLicense, 'utf8'));
output.push('\nChromium and Electron runtime notices are also distributed alongside llm4orTT.exe in LICENSE.electron.txt and LICENSES.chromium.html.');
function solverNotices(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) solverNotices(file);
    else if (/(license|copying|notice)/i.test(entry.name) && !/\.(pyc|py|pyd)$/i.test(entry.name)) output.push('\n' + file.replace(root, '') + '\n', fs.readFileSync(file, 'utf8'));
  }
}
if (fs.existsSync('runtime/python')) { output.push('\nBUNDLED PYTHON / PYOMO / HiGHS / NUMPY NOTICES\nVersions and hashes: docs/solver-lock.json. Gurobi is optional and is not redistributed.'); solverNotices(path.join(root, 'runtime/python')); }
fs.writeFileSync('THIRD_PARTY_NOTICES.txt', output.join('\n'));
fs.mkdirSync('docs', { recursive: true }); fs.writeFileSync('docs/dependencies.json', JSON.stringify(summary, null, 2));
console.log(JSON.stringify({ packages: summary.length, unresolvedLicenses: summary.filter(x => !x.license).map(x => x.name) }));
