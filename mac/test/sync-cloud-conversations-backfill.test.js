"use strict";

// One-time cloud conversations backfill (2026-06): the cloud ingest dropped
// `conversation_count` to 0 from 2026-04-18 until the field-mapping fix, and
// the only recoverable source is each user's local queue.jsonl. The migration
// resets the cloud upload offset exactly once so the next syncs replay the
// full queue; ingest's whole-row upsert overwrites historical buckets with
// correct conversation counts.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const {
  applyCloudConversationsBackfill,
  CLOUD_CONVERSATIONS_BACKFILL_KEY,
} = require("../src/commands/sync");

test("resets the upload offset exactly once and records the migration", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-conv-backfill-"));
  try {
    const queueStatePath = path.join(tmp, "queue.state.json");
    await fs.writeFile(queueStatePath, JSON.stringify({ offset: 123456, updatedAt: "x" }));
    const cursors = { version: 1 };

    const applied = await applyCloudConversationsBackfill({ cursors, queueStatePath });
    assert.equal(applied, true, "first run resets a non-zero offset");
    const state = JSON.parse(await fs.readFile(queueStatePath, "utf8"));
    assert.equal(state.offset, 0, "upload offset reset to replay the full queue");
    const marker = cursors.migrations[CLOUD_CONVERSATIONS_BACKFILL_KEY];
    assert.ok(marker?.appliedAt, "migration marker recorded");
    assert.equal(marker.previousOffset, 123456);

    // Second run is a no-op even if the offset has advanced again — the
    // replay must happen exactly once, not on every sync.
    await fs.writeFile(queueStatePath, JSON.stringify({ offset: 9999, updatedAt: "y" }));
    const appliedAgain = await applyCloudConversationsBackfill({ cursors, queueStatePath });
    assert.equal(appliedAgain, false);
    const state2 = JSON.parse(await fs.readFile(queueStatePath, "utf8"));
    assert.equal(state2.offset, 9999, "subsequent syncs keep their own offset");
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test("marks the migration without touching state when offset is already 0 / missing", async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "tt-conv-backfill-zero-"));
  try {
    const queueStatePath = path.join(tmp, "queue.state.json"); // never created
    const cursors = { version: 1 };
    const applied = await applyCloudConversationsBackfill({ cursors, queueStatePath });
    assert.equal(applied, false, "nothing to reset for fresh installs");
    assert.ok(cursors.migrations[CLOUD_CONVERSATIONS_BACKFILL_KEY]?.appliedAt);
    await assert.rejects(() => fs.readFile(queueStatePath, "utf8"), { code: "ENOENT" });
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});
