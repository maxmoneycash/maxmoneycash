const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const copyPath = path.join(root, "dashboard", "src", "content", "copy.csv");
const marketingLandingPath = path.join(
  root,
  "dashboard",
  "src",
  "ui",
  "marketing",
  "MarketingLanding.jsx",
);

function read(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function hasCopyKey(csv, key) {
  return csv.startsWith(`${key},`) || csv.includes(`\n${key},`);
}

test("landing CTA copy keys exist", () => {
  const csv = read(copyPath);
  const requiredKeys = ["landing.cta.primary", "landing.cta.secondary"];

  for (const key of requiredKeys) {
    assert.ok(hasCopyKey(csv, key), `expected copy registry to include ${key}`);
  }
});

test("Marketing landing uses CTA copy keys", () => {
  const source = read(marketingLandingPath);
  const requiredKeys = ["landing.cta.primary", "landing.cta.secondary"];

  for (const key of requiredKeys) {
    assert.ok(
      source.includes(`copy("${key}"`),
      `expected MarketingLanding to use copy key ${key}`,
    );
  }
});
