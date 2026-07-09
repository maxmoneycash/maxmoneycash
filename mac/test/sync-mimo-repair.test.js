const assert = require("node:assert/strict");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs/promises");
const { test } = require("node:test");

const { repairMimoClaudeMislabel } = require("../src/commands/sync");

// One-time repair for the 0.57.0 mimo mislabel bug: purge all source=mimo data
// (the mislabeled Claude mirror) from the local queues + cursor state so the
// next sync rebuilds source=mimo correctly with the providerID-filtered reader.

function row(source, model, hour, total) {
  return JSON.stringify({
    hour_start: hour,
    source,
    model,
    input_tokens: 0,
    output_tokens: 0,
    cached_input_tokens: 0,
    cache_creation_input_tokens: 0,
    reasoning_output_tokens: 0,
    total_tokens: total,
    conversation_count: 1,
  });
}

test("repairMimoClaudeMislabel: purges source=mimo from queue + state, keeps others, resets offset, idempotent", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-mimo-repair-"));
  try {
    const queuePath = path.join(tmp, "queue.jsonl");
    const queueStatePath = path.join(tmp, "queue.state.json");
    const projectQueuePath = path.join(tmp, "project.queue.jsonl");
    const projectQueueStatePath = path.join(tmp, "project.queue.state.json");

    const H = "2026-06-22T10:00:00Z";
    await fs.writeFile(
      queuePath,
      [
        row("claude", "claude-opus-4-8", H, 100), // keep
        row("mimo", "claude-opus-4-8", H, 999), // mislabeled — drop
        row("mimo", "mimo-auto", H, 50), // also dropped (rebuilt fresh next sync)
        row("codex", "gpt-5", H, 200), // keep
      ].join("\n") + "\n",
      "utf8",
    );
    await fs.writeFile(
      projectQueuePath,
      [
        JSON.stringify({ hour_start: H, source: "mimo", project: "p1", total_tokens: 999 }),
        JSON.stringify({ hour_start: H, source: "claude", project: "p1", total_tokens: 100 }),
      ].join("\n") + "\n",
      "utf8",
    );
    await fs.writeFile(queueStatePath, JSON.stringify({ offset: 4096 }) + "\n", "utf8");
    await fs.writeFile(projectQueueStatePath, JSON.stringify({ offset: 2048 }) + "\n", "utf8");

    const cursors = {
      version: 1,
      mimo: { messages: { "s|m": { lastTotals: {} } } },
      hourly: {
        version: 3,
        buckets: {
          [`mimo|claude-opus-4-8|${H}`]: { total_tokens: 999 },
          [`mimo|mimo-auto|${H}`]: { total_tokens: 50 },
          [`claude|claude-opus-4-8|${H}`]: { total_tokens: 100 },
        },
        groupQueued: { [`mimo|${H}`]: "k", [`claude|${H}`]: "k2" },
      },
      projectHourly: {
        buckets: { [`p1|mimo|${H}`]: { total_tokens: 999 }, [`p1|claude|${H}`]: { total_tokens: 100 } },
      },
      migrations: {},
    };

    const changed = await repairMimoClaudeMislabel({
      cursors,
      queuePath,
      queueStatePath,
      projectQueuePath,
      projectQueueStatePath,
    });
    assert.equal(changed, true);

    // Queue: all source=mimo rows gone; claude + codex preserved.
    const q = (await fs.readFile(queuePath, "utf8")).trim().split("\n").map((l) => JSON.parse(l));
    assert.deepEqual([...new Set(q.map((r) => r.source))].sort(), ["claude", "codex"]);
    const pq = (await fs.readFile(projectQueuePath, "utf8")).trim().split("\n").map((l) => JSON.parse(l));
    assert.deepEqual([...new Set(pq.map((r) => r.source))], ["claude"]);

    // Cursor state: mimo buckets cleared, others kept; cursors.mimo dropped.
    assert.ok(!Object.keys(cursors.hourly.buckets).some((k) => k.startsWith("mimo|")));
    assert.ok(cursors.hourly.buckets[`claude|claude-opus-4-8|${H}`]);
    assert.ok(!Object.keys(cursors.hourly.groupQueued).some((k) => k.startsWith("mimo|")));
    assert.ok(!Object.keys(cursors.projectHourly.buckets).some((k) => k.includes("|mimo|")));
    assert.equal(cursors.mimo, undefined);

    // Upload offsets reset for full replay.
    assert.equal(JSON.parse(await fs.readFile(queueStatePath, "utf8")).offset, 0);
    assert.equal(JSON.parse(await fs.readFile(projectQueueStatePath, "utf8")).offset, 0);

    // Backup of the main queue was written.
    const files = await fs.readdir(tmp);
    assert.ok(files.some((f) => f.startsWith("queue.jsonl.bak.")));

    // Migration sentinel set with counts.
    assert.equal(cursors.migrations.mimoClaudeMislabelRepair_2026_06.removedMain, 2);

    // Idempotent: second run is a no-op.
    const changed2 = await repairMimoClaudeMislabel({
      cursors, queuePath, queueStatePath, projectQueuePath, projectQueueStatePath,
    });
    assert.equal(changed2, false);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test("repairMimoClaudeMislabel: no mimo data → marks done without touching files", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-mimo-repair-noop-"));
  try {
    const queuePath = path.join(tmp, "queue.jsonl");
    await fs.writeFile(queuePath, row("claude", "claude-opus-4-8", "2026-06-22T10:00:00Z", 100) + "\n", "utf8");
    const cursors = { version: 1, hourly: { buckets: {} }, migrations: {} };
    const changed = await repairMimoClaudeMislabel({ cursors, queuePath, queueStatePath: path.join(tmp, "queue.state.json") });
    assert.equal(changed, false);
    assert.ok(cursors.migrations.mimoClaudeMislabelRepair_2026_06); // sentinel set
    // Queue untouched (no backup created).
    const files = await fs.readdir(tmp);
    assert.ok(!files.some((f) => f.includes(".bak.")));
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});
