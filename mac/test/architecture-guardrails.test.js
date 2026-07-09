const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

const { runGuardrails } = require("../scripts/validate-architecture-guardrails.cjs");

function writeFile(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf8");
}

test("guardrails flag service role keys", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "guardrails-"));
  writeFile(path.join(root, "dashboard", "app.jsx"), "const key = process.env.SERVICE_ROLE_KEY;\n");

  const { errors } = runGuardrails({ root });
  const codes = errors.map((err) => err.code).sort();
  assert.deepEqual(codes, ["SERVICE_ROLE_KEY"]);
});

test("guardrails flag SQL money and timestamp", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "guardrails-"));
  writeFile(
    path.join(root, "schema.sql"),
    "CREATE TABLE t (created_at timestamp, amount money);\n",
  );

  const { errors } = runGuardrails({ root });
  const codes = errors.map((err) => err.code);
  assert.ok(codes.includes("SQL_MONEY"));
  assert.ok(codes.includes("SQL_TIMESTAMP"));
});

test("guardrails allow timestamptz and timestamp with time zone", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "guardrails-"));
  writeFile(
    path.join(root, "schema.sql"),
    "CREATE TABLE t (created_at timestamptz, audited_at timestamp with time zone);\n",
  );

  const { errors } = runGuardrails({ root });
  assert.equal(errors.length, 0);
});

test("guardrails allow timestamp casts used with AT TIME ZONE", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "guardrails-"));
  writeFile(
    path.join(root, "schema.sql"),
    "SELECT (current_date::timestamp AT TIME ZONE 'utc') AS from_ts;\n",
  );

  const { errors } = runGuardrails({ root });
  assert.equal(errors.length, 0);
});
