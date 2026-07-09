"use strict";

// The six account-* edge endpoints must each honor an optional ?device_id=
// query param by narrowing activeDeviceIds to that one device — but ONLY when
// the id belongs to the JWT-verified user (the includes() guard). This is a
// static source check (the endpoints are Deno + InsForge SDK and can't run
// under node --test); it guarantees all six got the identical guarded narrow.

const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const assert = require("node:assert");

const ROOT = path.join(__dirname, "..");
const EDGE_DIR = "dashboard/edge-patches";

const ENDPOINTS = [
  "tokentracker-account-daily.ts",
  "tokentracker-account-summary.ts",
  "tokentracker-account-hourly.ts",
  "tokentracker-account-monthly.ts",
  "tokentracker-account-heatmap.ts",
  "tokentracker-account-model-breakdown.ts",
];

function readEdge(name) {
  return fs.readFileSync(path.join(ROOT, EDGE_DIR, name), "utf8");
}

test("every account-* endpoint reads device_id and guards it with includes()", () => {
  for (const name of ENDPOINTS) {
    const src = readEdge(name);
    assert.ok(
      src.includes('url.searchParams.get("device_id")'),
      `${name}: does not read the device_id query param`,
    );
    assert.ok(
      /activeDeviceIds\.includes\(\s*requestedDeviceId\s*\)/.test(src),
      `${name}: missing the includes(requestedDeviceId) ownership guard`,
    );
    assert.ok(
      /activeDeviceIds\s*=\s*\[\s*requestedDeviceId\s*\]/.test(src),
      `${name}: does not narrow activeDeviceIds to [requestedDeviceId]`,
    );
    assert.ok(
      src.includes("let activeDeviceIds"),
      `${name}: activeDeviceIds must be declared 'let' (not const) so the narrow can re-assign it`,
    );
  }
});

test("account-devices endpoint exists, verifies JWT, queries devices, sums per-device", () => {
  const src = readEdge("tokentracker-account-devices.ts");
  assert.ok(src.includes("verifiedUserIdFromJwt"), "missing JWT verification");
  assert.ok(
    src.includes('.from("tokentracker_devices")'),
    "does not query tokentracker_devices",
  );
  assert.ok(
    src.includes('.select("id, device_name, platform, created_at")'),
    "account-devices must select id, device_name, platform, created_at",
  );
  assert.ok(src.includes('.is("revoked_at", null)'), "must filter revoked devices");
  assert.ok(src.includes('.eq("user_id"'), "must filter devices by user_id");
  assert.ok(src.includes("account_usage_grouped"), "does not sum usage via the RPC");
  assert.ok(src.includes("total_tokens"), "does not return per-device total_tokens");
});

test("account-devices is NOT in the pricing-parity mirror set (no MODEL_PRICING block)", () => {
  const src = readEdge("tokentracker-account-devices.ts");
  assert.ok(!src.includes("const MODEL_PRICING"), "account-devices must not embed a pricing block");
});
