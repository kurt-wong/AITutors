#!/usr/bin/env node
/**
 * Validate every math string in the cached TeachingScripts with the same KaTeX
 * build the player uses. A schema-valid script can still contain LaTeX that
 * KaTeX refuses; this is the renderable-formula gate.
 *
 *   node tools/validate-katex.cjs "../Teaching Script Compiler/data"
 */
const fs = require("fs");
const path = require("path");
const katex = require("katex");

const dataDir = path.resolve(process.argv[2] || "../Teaching Script Compiler/data");
const indexPath = path.join(dataDir, "scripts", "index.json");

function splitMath(text) {
  const out = [];
  const re = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;
  let match;
  while ((match = re.exec(text)) !== null) {
    out.push((match[1] ?? match[2]).trim());
  }
  return out.filter(Boolean);
}

const rows = JSON.parse(fs.readFileSync(indexPath, "utf8"));
const results = [];
for (const row of rows) {
  if (row.validation !== "pass") continue;
  const script = JSON.parse(fs.readFileSync(path.join(dataDir, row.path), "utf8"));
  const samples = [];
  for (const step of script.steps) {
    for (const block of step.board) {
      if (block.kind === "math" && block.latex) samples.push(block.latex);
      if (block.text) samples.push(...splitMath(block.text));
      for (const line of block.rows ?? []) {
        for (const cell of line) samples.push(...splitMath(cell));
      }
    }
  }
  const failures = [];
  for (const latex of samples) {
    try {
      katex.renderToString(latex, { throwOnError: true, strict: "ignore" });
    } catch (error) {
      failures.push({ latex, message: String(error.message).slice(0, 200) });
    }
  }
  results.push({ question_id: script.question_id, samples: samples.length, failures });
}

const bad = results.filter((row) => row.failures.length > 0);
const summary = {
  scripts: results.length,
  mathSamples: results.reduce((sum, row) => sum + row.samples, 0),
  scriptsWithFailures: bad.length,
  failures: bad,
};
console.log(JSON.stringify(summary, null, 1));
process.exit(bad.length === 0 ? 0 : 1);
