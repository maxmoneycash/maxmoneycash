const assert = require("node:assert/strict");
const { test } = require("node:test");

const {
  DEFAULTS,
  normalizeState,
  decideAutoUpload,
  recordUploadSuccess,
  recordUploadFailure,
  parseRetryAfterMs,
} = require("../src/lib/upload-throttle");

test("normalizeState tolerates null/invalid values", () => {
  const s = normalizeState({
    lastSuccessMs: "nope",
    nextAllowedAtMs: -1,
    backoffUntilMs: 0,
    backoffStep: "2",
  });
  assert.equal(s.version, 1);
  assert.equal(s.lastSuccessMs, 0);
  assert.equal(s.nextAllowedAtMs, 0);
  assert.equal(s.backoffUntilMs, 0);
  assert.equal(s.backoffStep, 2);
});

test("decideAutoUpload blocks when no pending bytes", () => {
  const d = decideAutoUpload({ nowMs: 1000, pendingBytes: 0, state: {}, config: null });
  assert.equal(d.allowed, false);
  assert.equal(d.reason, "no-pending");
});

test("decideAutoUpload blocks until nextAllowedAtMs", () => {
  const nowMs = 1_000_000;
  const d = decideAutoUpload({
    nowMs,
    pendingBytes: 123,
    state: { nextAllowedAtMs: nowMs + 10_000 },
    config: null,
  });
  assert.equal(d.allowed, false);
  assert.equal(d.reason, "throttled");
  assert.equal(d.blockedUntilMs, nowMs + 10_000);
});

test("decideAutoUpload chooses large drain when backlogBytes reached", () => {
  const nowMs = 1_000_000;
  const d = decideAutoUpload({
    nowMs,
    pendingBytes: DEFAULTS.backlogBytes,
    state: { nextAllowedAtMs: 0 },
    config: null,
  });
  assert.equal(d.allowed, true);
  assert.equal(d.maxBatches, DEFAULTS.maxBatchesLarge);
  assert.equal(d.batchSize, DEFAULTS.batchSize);
});

test("recordUploadSuccess sets nextAllowedAtMs and resets backoff", () => {
  const nowMs = 10_000;
  const s = recordUploadSuccess({
    nowMs,
    state: { backoffStep: 3, backoffUntilMs: nowMs + 999_999 },
    randInt: () => 0,
  });
  assert.equal(s.lastSuccessMs, nowMs);
  assert.equal(s.backoffStep, 0);
  assert.equal(s.backoffUntilMs, 0);
  assert.equal(s.nextAllowedAtMs, nowMs + DEFAULTS.intervalMs);
});

test("recordUploadFailure uses Retry-After for 429", () => {
  const nowMs = 10_000;
  const s = recordUploadFailure({
    nowMs,
    state: { backoffStep: 0, nextAllowedAtMs: 0 },
    error: { status: 429, retryAfterMs: 120_000, message: "too many requests" },
  });
  assert.equal(s.backoffUntilMs, nowMs + 120_000);
  assert.equal(s.nextAllowedAtMs, nowMs + 120_000);
  assert.equal(s.backoffStep, 1);
  assert.ok(typeof s.lastErrorAt === "string" && s.lastErrorAt.length > 0);
  assert.ok(typeof s.lastError === "string" && s.lastError.includes("too many requests"));
});

test("recordUploadFailure exponential backoff on non-429", () => {
  const nowMs = 10_000;
  const s1 = recordUploadFailure({
    nowMs,
    state: { backoffStep: 0, nextAllowedAtMs: 0 },
    error: { status: 500, message: "server error" },
  });
  const s2 = recordUploadFailure({
    nowMs,
    state: s1,
    error: { status: 500, message: "server error" },
  });
  assert.equal(s1.backoffUntilMs, nowMs + DEFAULTS.backoffInitialMs);
  assert.equal(s2.backoffUntilMs, nowMs + DEFAULTS.backoffInitialMs * 2);
});

test("parseRetryAfterMs parses seconds and HTTP-date", () => {
  assert.equal(parseRetryAfterMs("2", 1000), 2000);
  const d = new Date(10_000).toUTCString();
  assert.equal(parseRetryAfterMs(d, 0), 10_000);
  assert.equal(parseRetryAfterMs("invalid"), null);
});
