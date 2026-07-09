#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

async function main() {
  const modulePath = path.resolve(__dirname, "../../dashboard/src/lib/backend-probe-scheduler.js");
  const moduleUrl = pathToFileURL(modulePath).href;
  const {
    createProbeCadence,
    resolveProbeCadenceConfig,
    DEFAULT_PROBE_INTERVAL_MS,
    DEFAULT_PROBE_MAX_INTERVAL_MS,
    DEFAULT_PROBE_FAILURE_RETRY_MS,
  } = await import(moduleUrl);

  const resolved = resolveProbeCadenceConfig({ intervalMs: DEFAULT_PROBE_INTERVAL_MS });
  assert.equal(resolved.baseIntervalMs, DEFAULT_PROBE_INTERVAL_MS);
  assert.equal(resolved.maxIntervalMs, DEFAULT_PROBE_MAX_INTERVAL_MS);
  assert.equal(resolved.failureRetryMs, DEFAULT_PROBE_FAILURE_RETRY_MS);

  const cadence = createProbeCadence({ intervalMs: DEFAULT_PROBE_INTERVAL_MS });
  assert.equal(cadence.getNextDelay(), 120_000);

  cadence.onSuccess();
  assert.equal(cadence.getNextDelay(), 120_000);

  cadence.onSuccess();
  assert.equal(cadence.getNextDelay(), 180_000);

  cadence.onSuccess();
  assert.equal(cadence.getNextDelay(), 240_000);

  cadence.onSuccess();
  assert.equal(cadence.getNextDelay(), 300_000);

  cadence.onSuccess();
  assert.equal(cadence.getNextDelay(), 300_000);

  cadence.onFailure();
  assert.equal(cadence.getNextDelay(), 10_000);

  cadence.onError();
  assert.equal(cadence.getNextDelay(), 120_000);

  process.stdout.write(
    JSON.stringify(
      {
        ok: true,
        config: cadence.getConfig(),
      },
      null,
      2,
    ) + "\n",
  );
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
