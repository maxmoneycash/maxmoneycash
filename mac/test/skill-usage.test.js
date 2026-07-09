const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { describe, it } = require("node:test");

const { scanSkillUsage } = require("../src/lib/skill-usage");

function makeHome() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "tt-skill-usage-"));
  fs.mkdirSync(path.join(home, ".claude", "projects", "proj"), { recursive: true });
  return home;
}

function assistantLine({ id, ts, model, skills, usage }) {
  return JSON.stringify({
    type: "assistant",
    timestamp: ts,
    message: {
      id,
      model,
      usage,
      content: skills.map((skill, i) => ({
        type: "tool_use",
        id: `${id}-blk${i}`,
        name: "Skill",
        input: { skill },
      })),
    },
  });
}

describe("scanSkillUsage", () => {
  it("counts invocations, splits a turn's usage across its skills, and dedupes by block id", async () => {
    const home = makeHome();
    const projDir = path.join(home, ".claude", "projects", "proj");

    const lineA = assistantLine({
      id: "msgA",
      ts: "2026-05-01T00:00:00.000Z",
      model: "claude-opus-4-6",
      skills: ["nothing-design"],
      usage: { input_tokens: 100, output_tokens: 50, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
    });
    const lineB = assistantLine({
      id: "msgB",
      ts: "2026-05-02T00:00:00.000Z",
      model: "claude-opus-4-6",
      skills: ["bash", "agent"],
      usage: { input_tokens: 200, output_tokens: 100, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
    });
    fs.writeFileSync(path.join(projDir, "session1.jsonl"), `${lineA}\n${lineB}\n`);
    // Duplicate of turn A in a second file (e.g. subagent copy) — must be deduped.
    fs.writeFileSync(path.join(projDir, "session2.jsonl"), `${lineA}\n`);

    const result = await scanSkillUsage({ home, force: true });

    assert.equal(result.scannedFiles, 2);
    assert.equal(result.totalInvocations, 3, "nothing-design + bash + agent, A counted once");
    assert.equal(result.skills.length, 3);

    const byName = Object.fromEntries(result.skills.map((s) => [s.skill, s]));
    assert.equal(byName["nothing-design"].invocations, 1, "deduped across files");
    assert.equal(byName["nothing-design"].tokens.input_tokens, 100);
    assert.equal(byName["nothing-design"].tokens.output_tokens, 50);
    assert.equal(byName["nothing-design"].lastUsedAt, "2026-05-01T00:00:00.000Z");

    // Turn B's usage (200/100) split evenly across its 2 skills → 100/50 each.
    assert.equal(byName.bash.tokens.input_tokens, 100);
    assert.equal(byName.bash.tokens.output_tokens, 50);
    assert.equal(byName.agent.tokens.input_tokens, 100);

    fs.rmSync(home, { recursive: true, force: true });
  });

  it("uses the fingerprint cache until files change", async () => {
    const home = makeHome();
    const projDir = path.join(home, ".claude", "projects", "proj");
    fs.writeFileSync(
      path.join(projDir, "s.jsonl"),
      `${assistantLine({ id: "m1", ts: "2026-05-01T00:00:00.000Z", model: "x", skills: ["foo"], usage: { input_tokens: 1, output_tokens: 1 } })}\n`,
    );

    const first = await scanSkillUsage({ home, force: true });
    assert.equal(first.cached, false);
    const second = await scanSkillUsage({ home });
    assert.equal(second.cached, true, "unchanged files → cache hit");
    assert.equal(second.totalInvocations, first.totalInvocations);

    fs.rmSync(home, { recursive: true, force: true });
  });
});
