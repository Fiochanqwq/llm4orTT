import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { analyzeControlledEvidence, renderControlledReport, sha256 } from './lib/evidence-statistics.mjs';

export function controlledReport(directory, { check = false } = {}) {
  const serialized = fs.readFileSync(path.join(directory, 'controlled-results.jsonl'), 'utf8');
  const protocolText = fs.readFileSync(path.join(directory, 'protocol.json'), 'utf8');
  const result = analyzeControlledEvidence(serialized, JSON.parse(protocolText));
  result.protocolSha256 = sha256(protocolText);
  const contents = { 'statistics.json': JSON.stringify(result, null, 2) + '\n', 'report.md': renderControlledReport(result) };
  for (const [name, content] of Object.entries(contents)) {
    const file = path.join(directory, name);
    if (check) assert.equal(fs.readFileSync(file, 'utf8'), content, 'Stale or modified report: ' + name);
    else fs.writeFileSync(file, content);
  }
  return { sourceSha256: result.source.sha256, files: Object.fromEntries(Object.entries(contents).map(([name, content]) => [name, sha256(content)])) };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    assert.ok(process.argv[2] && process.argv.slice(3).every(arg => arg === '--check'), 'Usage: node scripts/analyze-controlled-evidence.mjs DIRECTORY [--check]');
    console.log(JSON.stringify(controlledReport(path.resolve(process.argv[2]), { check: process.argv.includes('--check') })));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
