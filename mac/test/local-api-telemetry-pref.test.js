const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

const { createLocalApiHandler } = require("../src/lib/local-api");

async function callTelemetryPref(queuePath) {
  const handler = createLocalApiHandler({ queuePath });
  const url = new URL("http://localhost/functions/tokentracker-telemetry-pref");
  const req = { method: "GET", url: url.pathname, headers: { host: "localhost" } };
  const chunks = [];
  const res = {
    statusCode: 200,
    setHeader() {},
    writeHead() {},
    write(chunk) {
      chunks.push(chunk);
    },
    end(body) {
      if (body) chunks.push(body);
    },
  };
  const handled = await handler(req, res, url);
  assert.ok(handled, "telemetry-pref endpoint must be handled");
  return JSON.parse(chunks.join(""));
}

async function makeQueueDir() {
  const tmp = await fs.promises.mkdtemp(path.join(os.tmpdir(), "tt-telemetry-pref-"));
  const queuePath = path.join(tmp, "queue.jsonl");
  await fs.promises.writeFile(queuePath, "");
  return queuePath;
}

test("telemetry-pref reports enabled by default", async () => {
  const queuePath = await makeQueueDir();
  const body = await callTelemetryPref(queuePath);
  assert.deepEqual(body, { disabled: false });
});

test("telemetry-pref reflects config.json telemetry:false", async () => {
  const queuePath = await makeQueueDir();
  await fs.promises.writeFile(
    path.join(path.dirname(queuePath), "config.json"),
    JSON.stringify({ telemetry: false }),
  );
  const body = await callTelemetryPref(queuePath);
  assert.deepEqual(body, { disabled: true });
});

test("telemetry-pref reflects TOKENTRACKER_NO_TELEMETRY env", async () => {
  const queuePath = await makeQueueDir();
  const prev = process.env.TOKENTRACKER_NO_TELEMETRY;
  process.env.TOKENTRACKER_NO_TELEMETRY = "1";
  try {
    const body = await callTelemetryPref(queuePath);
    assert.deepEqual(body, { disabled: true });
  } finally {
    if (prev === undefined) delete process.env.TOKENTRACKER_NO_TELEMETRY;
    else process.env.TOKENTRACKER_NO_TELEMETRY = prev;
  }
});

test("telemetry-pref survives corrupt config.json", async () => {
  const queuePath = await makeQueueDir();
  await fs.promises.writeFile(path.join(path.dirname(queuePath), "config.json"), "{not json");
  const body = await callTelemetryPref(queuePath);
  assert.deepEqual(body, { disabled: false });
});
