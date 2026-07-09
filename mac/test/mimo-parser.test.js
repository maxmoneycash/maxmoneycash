const assert = require("node:assert/strict");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs/promises");
const cp = require("node:child_process");
const { test } = require("node:test");

const {
  parseOpencodeDbIncremental,
  readMimoDbMessages,
} = require("../src/lib/rollout");

// ─────────────────────────────────────────────────────────────────────────────
// Mimo — mimocode (Xiaomi MiMo, OpenCode-fork SQLite at ~/.local/share/mimocode/mimocode.db)
//
// mimocode mirrors the user's Claude Code + claude-mem history into its own
// `message` table (claude_import AND a live observer/session sync), so most
// rows are claude-* turns (providerID="anthropic") the Claude parser already
// counts as source=claude. readMimoDbMessages keeps ONLY mimo's own-model rows,
// or Claude usage is double-counted and mislabeled as mimo.
//
// CRUCIAL: the rule keys on providerID, NOT the model id. A mimo-named model
// the user runs INSIDE Claude Code (e.g. model=mimo-v2.5-pro, providerID
// "anthropic") is logged in ~/.claude and already counted as source=claude, so
// it MUST be dropped here. Only providerID mimo|xiaomi is genuine mimo usage.
// ─────────────────────────────────────────────────────────────────────────────

function buildMimoDb(dbPath, messageRows) {
  const schema = `
    CREATE TABLE message (
      id text PRIMARY KEY,
      session_id text NOT NULL,
      time_created integer NOT NULL,
      time_updated integer NOT NULL,
      data text NOT NULL
    );
  `;
  cp.execFileSync("sqlite3", [dbPath, schema], { encoding: "utf8" });
  for (const row of messageRows) {
    const dataJson = JSON.stringify(row.data).replace(/'/g, "''");
    const sql = `INSERT INTO message VALUES('${row.id}','${row.session_id}',${row.time_created},${row.time_updated},'${dataJson}');`;
    cp.execFileSync("sqlite3", [dbPath, sql], { encoding: "utf8" });
  }
}

function assistantRow(id, sessionID, modelID, providerID, tokens, ts) {
  return {
    id,
    session_id: sessionID,
    time_created: ts,
    time_updated: ts + 1,
    data: {
      id,
      sessionID,
      role: "assistant",
      modelID,
      providerID,
      cost: 0,
      tokens,
      time: { created: ts, completed: ts + 100 },
      path: { cwd: "/tmp/proj", root: "/tmp/proj" },
    },
  };
}

const T = (input, output, read = 0, write = 0, reasoning = 0) => ({
  input,
  output,
  reasoning,
  cache: { read, write },
  total: input + output + reasoning + read + write,
});

test("Mimo: readMimoDbMessages keeps only mimo-native rows, drops mirrored Claude data", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-mimo-"));
  try {
    const dbPath = path.join(tmp, "mimocode.db");
    const ts = 1780538800000;
    buildMimoDb(dbPath, [
      // Mirrored Claude Code / claude-mem rows — providerID=anthropic. Must be
      // dropped (already counted as source=claude), even with NO claude_import
      // table present (mimo also mirrors Claude via observer/session sync).
      assistantRow("msg_c1", "ses_obs", "claude-haiku-4-5-20251001", "anthropic", T(10, 300, 800000, 5000), ts),
      assistantRow("msg_c2", "ses_proj", "claude-opus-4-8", "anthropic", T(1000, 5000, 900000, 50000), ts + 500),
      // CRUCIAL: a mimo-named model run INSIDE Claude Code is logged with
      // providerID=anthropic (it's in ~/.claude, counted as source=claude).
      // Must be DROPPED here — keying off the model id would double-count it.
      assistantRow("msg_c3", "ses_proj", "mimo-v2.5-pro", "anthropic", T(200, 50, 0, 0), ts + 700),
      // Genuine mimo usage — mimo's own router (providerID=mimo).
      assistantRow("msg_m1", "ses_mimo", "mimo-auto", "mimo", T(500, 25, 100, 0), ts + 1000),
      // Xiaomi-provider mimo variant — kept.
      assistantRow("msg_m3", "ses_mimo", "mimo-v2.5-pro-ultraspeed", "xiaomi", T(30, 10, 0, 0), ts + 2000),
    ]);

    const dbMessages = readMimoDbMessages(dbPath);
    const ids = new Set(dbMessages.map((m) => m.id));
    assert.equal(dbMessages.length, 2, "only the 2 providerID=mimo|xiaomi rows");
    assert.ok(!ids.has("msg_c1"), "mirrored claude-haiku must be dropped");
    assert.ok(!ids.has("msg_c2"), "mirrored claude-opus must be dropped");
    assert.ok(!ids.has("msg_c3"), "mimo-v2.5-pro used in Claude Code (providerID=anthropic) MUST be dropped");
    assert.ok(ids.has("msg_m1"), "mimo-auto (providerID=mimo) kept");
    assert.ok(ids.has("msg_m3"), "xiaomi-provider mimo variant kept");

    const queuePath = path.join(tmp, "queue.jsonl");
    const cursors = { version: 1 };
    const result = await parseOpencodeDbIncremental({
      dbMessages,
      cursors,
      queuePath,
      source: "mimo",
      cursorKey: "mimo",
    });
    assert.equal(result.eventsAggregated, 2);

    const queueLines = (await fs.readFile(queuePath, "utf8")).trim().split("\n").map((l) => JSON.parse(l));
    const sources = new Set(queueLines.map((r) => r.source));
    const models = new Set(queueLines.map((r) => r.model));
    assert.deepEqual([...sources], ["mimo"]);
    assert.ok(models.has("mimo-auto"));
    assert.ok(models.has("mimo-v2.5-pro-ultraspeed"));
    assert.ok(
      !models.has("mimo-v2.5-pro") && !models.has("claude-opus-4-8") && !models.has("claude-haiku-4-5-20251001"),
      "no anthropic-endpoint rows under mimo",
    );

    // tokens: only the 2 providerID=mimo|xiaomi rows (625 + 40); anthropic rows excluded.
    const totalAll = queueLines.reduce((a, r) => a + (r.total_tokens || 0), 0);
    assert.equal(totalAll, 625 + 40);

    // Idempotent re-run + cursor isolated under the `mimo` namespace.
    const result2 = await parseOpencodeDbIncremental({
      dbMessages, cursors, queuePath, source: "mimo", cursorKey: "mimo",
    });
    assert.equal(result2.eventsAggregated, 0);
    assert.ok(cursors.mimo && cursors.mimo.messages["ses_mimo|msg_m1"]);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test("Mimo: cursor namespace `mimo` is isolated from a pre-seeded opencode index", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-mimo-iso-"));
  try {
    const dbPath = path.join(tmp, "mimocode.db");
    const ts = 1780538800000;
    buildMimoDb(dbPath, [
      assistantRow("msg_m1", "ses_a", "mimo-auto", "mimo", T(500, 25, 100, 0), ts),
    ]);
    const dbMessages = readMimoDbMessages(dbPath);
    const cursors = {
      version: 1,
      opencode: {
        messages: { "ses_a|msg_m1": { lastTotals: { input_tokens: 500 }, updatedAt: new Date().toISOString() } },
        updatedAt: new Date().toISOString(),
      },
    };
    const queuePath = path.join(tmp, "queue.jsonl");
    const result = await parseOpencodeDbIncremental({ dbMessages, cursors, queuePath, source: "mimo", cursorKey: "mimo" });
    assert.equal(result.eventsAggregated, 1, "opencode pre-seed must not block the mimo namespace");
    assert.ok(cursors.opencode.messages["ses_a|msg_m1"], "opencode cursor untouched");
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});
