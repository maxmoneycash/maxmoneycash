#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.join(__dirname);
const SELF = path.basename(__filename);

function parseArgs(argv) {
  const opts = {
    list: false,
    pretty: false,
    only: [],
    exclude: [],
    filter: [],
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--list") {
      opts.list = true;
      continue;
    }
    if (arg === "--pretty" || arg === "--json-pretty") {
      opts.pretty = true;
      continue;
    }
    if (arg.startsWith("--only")) {
      const value = readValue(arg, argv, i);
      if (value.usedNext) i += 1;
      opts.only.push(...splitList(value.value));
      continue;
    }
    if (arg.startsWith("--exclude")) {
      const value = readValue(arg, argv, i);
      if (value.usedNext) i += 1;
      opts.exclude.push(...splitList(value.value));
      continue;
    }
    if (arg.startsWith("--filter")) {
      const value = readValue(arg, argv, i);
      if (value.usedNext) i += 1;
      opts.filter.push(...splitList(value.value));
      continue;
    }
  }

  return opts;
}

function readValue(arg, argv, idx) {
  const eq = arg.indexOf("=");
  if (eq !== -1) {
    return { value: arg.slice(eq + 1), usedNext: false };
  }
  const next = argv[idx + 1];
  if (next && !next.startsWith("--")) {
    return { value: next, usedNext: true };
  }
  return { value: "", usedNext: false };
}

function splitList(value) {
  if (!value) return [];
  return String(value)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function listTests() {
  return fs
    .readdirSync(ROOT)
    .filter((file) => file.endsWith(".cjs"))
    .filter((file) => file !== SELF)
    .map((file) => ({
      id: path.basename(file, ".cjs"),
      file,
    }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

function matchesAny(value, patterns) {
  if (!patterns.length) return true;
  const needle = String(value).toLowerCase();
  return patterns.some((pattern) => needle.includes(String(pattern).toLowerCase()));
}

function filterTests(tests, opts) {
  let selected = tests;

  if (opts.only.length) {
    const onlySet = new Set(opts.only.map((item) => item.toLowerCase()));
    selected = selected.filter((test) => onlySet.has(test.id.toLowerCase()));
  }

  if (opts.filter.length) {
    selected = selected.filter((test) => matchesAny(test.id, opts.filter));
  }

  if (opts.exclude.length) {
    const excludeSet = new Set(opts.exclude.map((item) => item.toLowerCase()));
    selected = selected.filter((test) => !excludeSet.has(test.id.toLowerCase()));
  }

  return selected;
}

function truncate(value, max = 4000) {
  const text = String(value || "");
  if (text.length <= max) return text;
  return `${text.slice(0, max)}\n...truncated ${text.length - max} chars`;
}

function runTest(test) {
  const start = Date.now();
  const result = spawnSync(process.execPath, [path.join(ROOT, test.file)], {
    encoding: "utf8",
    stdio: "pipe",
    env: process.env,
  });
  const durationMs = Date.now() - start;

  return {
    id: test.id,
    file: test.file,
    ok: result.status === 0,
    status: result.status,
    duration_ms: durationMs,
    stdout: truncate(result.stdout),
    stderr: truncate(result.stderr),
  };
}

function printUsage() {
  process.stdout.write(
    [
      "Usage: node scripts/acceptance/run-acceptance.cjs [options]",
      "",
      "Options:",
      "  --list                List available acceptance tests",
      "  --only a,b            Run only the given test ids",
      "  --filter substring    Run tests matching substring",
      "  --exclude a,b         Exclude the given test ids",
      "  --pretty              Pretty-print JSON output",
      "",
    ].join("\n") + "\n",
  );
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const tests = listTests();

  if (opts.list) {
    process.stdout.write(`${tests.map((t) => t.id).join("\n")}\n`);
    return;
  }

  const selected = filterTests(tests, opts);
  if (!selected.length) {
    printUsage();
    process.stderr.write("No matching acceptance tests.\n");
    process.exit(1);
    return;
  }

  const start = Date.now();
  const results = selected.map(runTest);
  const durationMs = Date.now() - start;

  const passed = results.filter((r) => r.ok).length;
  const failed = results.length - passed;

  const summary = {
    ok: failed === 0,
    total: results.length,
    passed,
    failed,
    duration_ms: durationMs,
    results,
  };

  const json = JSON.stringify(summary, null, opts.pretty ? 2 : 0);
  process.stdout.write(`${json}\n`);
  if (failed > 0) process.exit(1);
}

main().catch((err) => {
  process.stderr.write(`${err && err.stack ? err.stack : String(err)}\n`);
  process.exit(1);
});
