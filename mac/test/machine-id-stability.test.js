"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const {
  computeStableMachineId,
  getOrCreateMachineId,
  isLinuxContainer,
  isValidLinuxMachineId,
  defaultSeedPath,
} = require("../src/lib/machine-id");

const IOREG_SAMPLE = [
  "+-o J316sAP  <class IOPlatformExpertDevice, id 0x100000113, registered, matched, active, busy 0 (1234 ms), retain 38>",
  "  {",
  '    "IOPlatformUUID" = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEFFFF0001"',
  '    "model" = <"Mac14,10">',
  "  }",
].join("\n");

const REG_SAMPLE = [
  "",
  "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography",
  "    MachineGuid    REG_SZ    aaaaaaaa-bbbb-cccc-dddd-eeeeffff0001",
  "",
].join("\r\n");

const NOT_A_CONTAINER = { env: {}, pathExists: () => false, readFile: () => "0::/init.scope" };

async function mkTempTracker(prefix) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), prefix));
  return {
    dir,
    queuePath: path.join(dir, ".tokentracker", "tracker", "queue.jsonl"),
    configPath: path.join(dir, ".tokentracker", "tracker", "config.json"),
    seedPath: path.join(dir, ".config", "tokentracker", "machine-id"),
    async cleanup() {
      await fs.rm(dir, { recursive: true, force: true });
    },
  };
}

test("computeStableMachineId derives a deterministic hash from macOS IOPlatformUUID", () => {
  const opts = { platform: "darwin", execFile: () => IOREG_SAMPLE, username: "alice" };
  const first = computeStableMachineId(opts);
  const second = computeStableMachineId(opts);
  assert.match(first, /^[0-9a-f]{64}$/, "must be a hex sha256 digest, not the raw hardware UUID");
  assert.equal(first, second, "same hardware + user must always produce the same id");
  assert.ok(!first.includes("AAAAAAAA"), "raw hardware UUID must not leak into the id");
});

test("computeStableMachineId derives a deterministic hash from Windows MachineGuid", () => {
  const opts = { platform: "win32", execFile: () => REG_SAMPLE, username: "alice" };
  const first = computeStableMachineId(opts);
  assert.match(first, /^[0-9a-f]{64}$/);
  assert.equal(first, computeStableMachineId(opts));
});

test("computeStableMachineId derives a deterministic hash from a valid Linux machine-id", () => {
  const opts = {
    platform: "linux",
    username: "alice",
    ...NOT_A_CONTAINER,
    readFile: (p) => {
      if (p === "/proc/1/cgroup") return "0::/init.scope";
      if (p === "/etc/machine-id") return "0123456789abcdef0123456789abcdef\n";
      throw new Error("ENOENT");
    },
  };
  const first = computeStableMachineId(opts);
  assert.match(first, /^[0-9a-f]{64}$/);
  assert.equal(first, computeStableMachineId(opts));
});

test("computeStableMachineId salts with the OS username so co-located users get distinct devices", () => {
  const a = computeStableMachineId({ platform: "darwin", execFile: () => IOREG_SAMPLE, username: "alice" });
  const b = computeStableMachineId({ platform: "darwin", execFile: () => IOREG_SAMPLE, username: "bob" });
  assert.notEqual(a, b);
});

test("computeStableMachineId returns null when the OS identifier is unavailable", () => {
  assert.equal(
    computeStableMachineId({
      platform: "darwin",
      execFile: () => {
        throw new Error("spawn failed");
      },
    }),
    null,
  );
  assert.equal(computeStableMachineId({ platform: "darwin", execFile: () => "no uuid here" }), null);
});

test("computeStableMachineId rejects placeholder Linux machine-ids from cloned images", () => {
  for (const bogus of ["00000000000000000000000000000000", "uninitialized", "ffffffffffffffffffffffffffffffff", ""]) {
    const got = computeStableMachineId({
      platform: "linux",
      username: "alice",
      ...NOT_A_CONTAINER,
      readFile: (p) => {
        if (p === "/proc/1/cgroup") return "0::/init.scope";
        return `${bogus}\n`;
      },
    });
    assert.equal(got, null, `placeholder machine-id ${JSON.stringify(bogus)} must not become a device identity`);
  }
});

test("computeStableMachineId returns null inside containers (shared machine-id would merge devices)", () => {
  const validId = "0123456789abcdef0123456789abcdef";
  const containers = [
    { env: { container: "podman" }, pathExists: () => false, readFile: () => validId },
    { env: {}, pathExists: (p) => p === "/.dockerenv", readFile: () => validId },
    {
      env: {},
      pathExists: () => false,
      readFile: (p) => (p === "/proc/1/cgroup" ? "12:pids:/docker/abc123" : validId),
    },
  ];
  for (const signals of containers) {
    assert.equal(computeStableMachineId({ platform: "linux", username: "alice", ...signals }), null);
  }
});

test("isLinuxContainer / isValidLinuxMachineId guard helpers", () => {
  assert.equal(isLinuxContainer(NOT_A_CONTAINER), false);
  assert.equal(isLinuxContainer({ env: {}, pathExists: () => false, readFile: () => "1:name=systemd:/kubepods/x" }), true);
  assert.equal(isValidLinuxMachineId("0123456789abcdef0123456789abcdef"), true);
  assert.equal(isValidLinuxMachineId("0123456789ABCDEF0123456789ABCDEF"), true, "dbus ids are lowercased before use");
  assert.equal(isValidLinuxMachineId("0123"), false);
  assert.equal(isValidLinuxMachineId("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), false);
});

test("getOrCreateMachineId survives uninstall --purge via the hardware fingerprint", async (t) => {
  if (!computeStableMachineId()) {
    t.skip("no stable OS machine identifier on this host");
    return;
  }
  const tmp = await mkTempTracker("machine-id-hw-");
  try {
    const before = getOrCreateMachineId(tmp.queuePath);
    assert.ok(typeof before === "string" && before.length >= 8);

    // Simulate `uninstall --purge` + reinstall with the seed ALSO gone — the
    // hardware fingerprint alone must recover the identity.
    await fs.rm(path.join(tmp.dir, ".tokentracker"), { recursive: true, force: true });
    await fs.rm(tmp.seedPath, { force: true });
    const after = getOrCreateMachineId(tmp.queuePath);

    assert.equal(after, before, "reinstall after purge must recover the same machine id (issue #176)");
  } finally {
    await tmp.cleanup();
  }
});

test("getOrCreateMachineId recovers a legacy random id from the seed file after purge", async () => {
  const tmp = await mkTempTracker("machine-id-seed-");
  try {
    // stableMachineId: null simulates a host with no hardware identity — the
    // first install minted a random UUID (exactly the legacy situation).
    const before = getOrCreateMachineId(tmp.queuePath, { stableMachineId: null });
    assert.ok(typeof before === "string" && before.length >= 8);
    assert.equal((await fs.readFile(tmp.seedPath, "utf8")).trim(), before, "seed file must mirror the active id");

    // `uninstall --purge` removes ~/.tokentracker but NOT the seed.
    await fs.rm(path.join(tmp.dir, ".tokentracker"), { recursive: true, force: true });

    // Reinstall must prefer the seed over a freshly derived hardware id, so
    // the cloud device row anchored to the legacy id keeps matching.
    const after = getOrCreateMachineId(tmp.queuePath, { stableMachineId: "hash-of-new-hardware-id" });
    assert.equal(after, before, "seed recovery must win over hardware derivation (Codex P1)");
  } finally {
    await tmp.cleanup();
  }
});

test("getOrCreateMachineId seeds existing installs that predate the seed file", async () => {
  const tmp = await mkTempTracker("machine-id-migrate-");
  try {
    const legacy = "legacy-random-uuid-1234";
    await fs.mkdir(path.dirname(tmp.configPath), { recursive: true });
    await fs.writeFile(tmp.configPath, JSON.stringify({ machineId: legacy, deviceToken: "tok" }));

    assert.equal(
      getOrCreateMachineId(tmp.queuePath),
      legacy,
      "existing installs must not be migrated — their cloud device row is anchored to the old id",
    );
    assert.equal(
      (await fs.readFile(tmp.seedPath, "utf8")).trim(),
      legacy,
      "the legacy id must be mirrored to the purge-surviving seed (Codex P1 migration)",
    );
    const config = JSON.parse(await fs.readFile(tmp.configPath, "utf8"));
    assert.equal(config.deviceToken, "tok", "config must not be clobbered by the mirroring pass");
  } finally {
    await tmp.cleanup();
  }
});

test("defaultSeedPath stays inside the queue path's home and outside ~/.tokentracker", () => {
  const seed = defaultSeedPath("/Users/alice/.tokentracker/tracker/queue.jsonl");
  assert.equal(seed, path.join("/Users/alice", ".config", "tokentracker", "machine-id"));
  assert.ok(!seed.includes(".tokentracker"), "seed must survive `rm -rf ~/.tokentracker`");
});

test("local-api re-exports the machine-id helpers (back-compat for existing callers)", () => {
  const localApi = require("../src/lib/local-api");
  assert.equal(localApi.getOrCreateMachineId, getOrCreateMachineId);
  assert.equal(localApi.computeStableMachineId, computeStableMachineId);
});
