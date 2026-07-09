const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const required = [
  path.resolve("docs/screenshots/dashboard-dark.png"),
  path.resolve("docs/screenshots/dashboard-light.png"),
];

test("visual baselines exist", () => {
  for (const file of required) {
    assert.ok(fs.existsSync(file), `missing baseline: ${file}`);
  }
});
