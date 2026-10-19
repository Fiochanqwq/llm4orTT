import fs from 'node:fs';
import path from 'node:path';
import { build } from 'rolldown';
const root = process.cwd(), stage = path.join(root, 'build/stage');
if (!stage.startsWith(root + path.sep) || path.basename(stage) !== 'stage') throw Error('Invalid staging path');
// fs.rmSync can silently do nothing (observed in a restricted shell), which is how five generations of
// stale chunks ended up inside one package. Delete explicitly and prove the directory is gone.
function removeTree(target) {
  let stat;
  try { stat = fs.lstatSync(target); } catch { return; }
  if (stat.isDirectory() && !stat.isSymbolicLink()) {
    for (const name of fs.readdirSync(target)) removeTree(path.join(target, name));
    fs.rmdirSync(target);
  } else { try { fs.chmodSync(target, 0o666); } catch { } fs.unlinkSync(target); }
}
if (fs.existsSync(stage)) {
  if (fs.lstatSync(stage).isSymbolicLink() || fs.realpathSync(stage) !== path.join(fs.realpathSync(root), 'build', 'stage')) throw Error('Staging directory must be inside this project');
  removeTree(stage);
  if (fs.existsSync(stage)) throw Error('Staging directory could not be removed: ' + stage);
}
fs.mkdirSync(path.join(stage, 'server'), { recursive: true });
await build({ input: { launcher: 'server/launcher.mjs', http: 'server/http.mjs', providers: 'server/providers.mjs' }, platform: 'node',
  output: { dir: path.join(stage, 'server'), format: 'esm', entryFileNames: '[name].mjs', chunkFileNames: '[name]-[hash].mjs', minify: false, polyfillRequire: true },
  onwarn(warning, warn) { if (warning.code === 'UNRESOLVED_IMPORT') throw Error(warning.message); warn(warning); }
});
// Avoid the native recursive cp path, which can fail on Windows workspace paths.
function copyDirectory(source, destination) {
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name), to = path.join(destination, entry.name);
    if (entry.isDirectory()) copyDirectory(from, to);
    else fs.copyFileSync(from, to);
  }
}
copyDirectory(path.join(root, 'electron'), path.join(stage, 'electron'));
copyDirectory(path.join(root, 'dist/assets'), path.join(stage, 'dist/assets'));
for (const file of ['index.html', 'saturn-icon.png', 'saturn.svg']) fs.copyFileSync(path.join(root, 'dist', file), path.join(stage, 'dist', file));
fs.mkdirSync(path.join(stage, 'shared'), { recursive: true });
fs.copyFileSync('shared/providers.json', path.join(stage, 'shared/providers.json'));
// A stale dist is the one thing that must never reach the package, and internal docs must not ship.
const assets = path.join(stage, 'dist', 'assets');
if (!fs.existsSync(assets)) throw Error('dist/assets is missing; run npm run build first');
const bundles = fs.readdirSync(assets).filter(name => /^index-.*\.js$/.test(name));
if (bundles.length !== 1) throw Error('dist/assets contains ' + bundles.length + ' index-*.js bundles (expected 1); clear dist and rebuild');
for (const file of ['README.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.txt']) fs.copyFileSync(file, path.join(stage, file));
fs.copyFileSync('package-lock.json',path.join(stage,'dependency-lock.json'));
fs.copyFileSync('server/secrets.ps1', path.join(stage, 'server/secrets.ps1'));
const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const { name, version, description, author, license, type, main } = pkg;
// Dependencies are already bundled; the distribution never contains development node_modules.
fs.writeFileSync(path.join(stage, 'package.json'), JSON.stringify({ name, version, description, author, license, type, main }, null, 2));
console.log('Staged self-contained application: ' + stage);
