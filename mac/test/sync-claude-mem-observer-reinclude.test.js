const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

const {
  CLAUDE_MEM_OBSERVER_REINCLUDE_KEY,
  reincludeClaudeMemObserverFiles,
} = require("../src/commands/sync");

test("reincludeClaudeMemObserverFiles resets observer cursors, removes hashes, and relabels queue rows", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-claude-mem-reinclude-"));
  try {
    const observerDir = path.join(tmp, "-Users-x--claude-mem-observer-sessions");
    const normalDir = path.join(tmp, "-Users-x-some-project");
    await fs.mkdir(observerDir, { recursive: true });
    await fs.mkdir(normalDir, { recursive: true });

    const observerPath = path.join(observerDir, "observer.jsonl");
    const normalPath = path.join(normalDir, "normal.jsonl");
    await fs.writeFile(
      observerPath,
      JSON.stringify({
        timestamp: "2026-05-01T00:00:00.000Z",
        requestId: "req_observer",
        message: {
          id: "msg_observer",
          usage: { input_tokens: 10, output_tokens: 2 },
        },
      }) + "\n",
      "utf8",
    );
    await fs.writeFile(normalPath, "", "utf8");

    const queuePath = path.join(tmp, "queue.jsonl");
    await fs.writeFile(
      queuePath,
      [
        JSON.stringify({ source: "claude-mem", model: "claude-sonnet-4-5", input_tokens: 10 }),
        JSON.stringify({ source: "claude", model: "claude-sonnet-4-5", input_tokens: 5 }),
        JSON.stringify({ source: "claude-mem", model: "claude-sonnet-4-5", input_tokens: 7 }),
      ].join("\n") + "\n",
      "utf8",
    );

    const cursors = {
      version: 1,
      files: {
        [observerPath]: { inode: 1, offset: 100 },
        [normalPath]: { inode: 2, offset: 200 },
      },
      claudeHashes: ["msg_observer:req_observer", "msg_normal:req_normal"],
      migrations: {},
    };

    const changed = await reincludeClaudeMemObserverFiles({
      cursors,
      claudeFiles: [observerPath, normalPath],
      queuePath,
    });

    assert.equal(changed, true);
    assert.equal(cursors.files[observerPath], undefined);
    assert.deepEqual(cursors.files[normalPath], { inode: 2, offset: 200 });
    assert.deepEqual(cursors.claudeHashes, ["msg_normal:req_normal"]);

    const migration = cursors.migrations[CLAUDE_MEM_OBSERVER_REINCLUDE_KEY];
    assert.equal(migration.filesReset, 1);
    assert.equal(migration.hashesRemoved, 1);
    assert.equal(migration.queueRowsRelabeled, 2);

    const rewritten = (await fs.readFile(queuePath, "utf8"))
      .split("\n")
      .filter(Boolean)
      .map((l) => JSON.parse(l));
    assert.deepEqual(
      rewritten.map((r) => r.source),
      ["claude", "claude", "claude"],
    );
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test("reincludeClaudeMemObserverFiles remaps the upload offset to a line boundary in the rewritten queue", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-claude-mem-reinclude-offset-"));
  try {
    const queuePath = path.join(tmp, "queue.jsonl");
    const queueStatePath = path.join(tmp, "queue.state.json");

    const row1 = JSON.stringify({ source: "claude-mem", model: "claude-sonnet-4-5", input_tokens: 10 });
    const row2 = JSON.stringify({ source: "claude", model: "claude-sonnet-4-5", input_tokens: 5 });
    const row3 = JSON.stringify({ source: "claude-mem", model: "claude-sonnet-4-5", input_tokens: 7 });
    await fs.writeFile(queuePath, [row1, row2, row3].join("\n") + "\n", "utf8");

    // Old offset points mid-row3 (rows 1+2 uploaded, row3 partially "read" —
    // a non-boundary position must round DOWN so no row is ever skipped).
    const boundaryAfterRow2 = Buffer.byteLength(row1 + "\n" + row2 + "\n", "utf8");
    const midRow3 = boundaryAfterRow2 + 5;
    await fs.writeFile(queueStatePath, JSON.stringify({ offset: midRow3 }), "utf8");

    const cursors = { version: 1, files: {}, claudeHashes: [], migrations: {} };
    const changed = await reincludeClaudeMemObserverFiles({
      cursors,
      claudeFiles: [],
      queuePath,
      queueStatePath,
    });
    assert.equal(changed, true);

    const rewrittenRaw = await fs.readFile(queuePath, "utf8");
    const rewritten = rewrittenRaw.split("\n").filter(Boolean).map((l) => JSON.parse(l));
    assert.deepEqual(rewritten.map((r) => r.source), ["claude", "claude", "claude"]);
    assert.deepEqual(rewritten.map((r) => r.input_tokens), [10, 5, 7]);

    const state = JSON.parse(await fs.readFile(queueStatePath, "utf8"));
    // New offset must land exactly on the rewritten rows-1+2 boundary...
    const newRow1 = JSON.stringify({ source: "claude", model: "claude-sonnet-4-5", input_tokens: 10 });
    const expectedOffset = Buffer.byteLength(newRow1 + "\n" + row2 + "\n", "utf8");
    assert.equal(state.offset, expectedOffset);
    // ...so the unsent remainder is exactly the relabeled row3 — nothing lost.
    const remainder = Buffer.from(rewrittenRaw, "utf8").subarray(state.offset).toString("utf8");
    assert.deepEqual(
      remainder.split("\n").filter(Boolean).map((l) => JSON.parse(l)),
      [{ source: "claude", model: "claude-sonnet-4-5", input_tokens: 7 }],
    );
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test("reincludeClaudeMemObserverFiles is idempotent on second run", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-claude-mem-reinclude-idem-"));
  try {
    const cursors = { migrations: {}, files: {}, claudeHashes: [] };
    const queuePath = path.join(tmp, "queue.jsonl");
    await fs.writeFile(queuePath, "", "utf8");

    await reincludeClaudeMemObserverFiles({ cursors, claudeFiles: [], queuePath });
    const firstAt = cursors.migrations[CLAUDE_MEM_OBSERVER_REINCLUDE_KEY].appliedAt;

    await reincludeClaudeMemObserverFiles({ cursors, claudeFiles: [], queuePath });
    assert.equal(cursors.migrations[CLAUDE_MEM_OBSERVER_REINCLUDE_KEY].appliedAt, firstAt);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});
