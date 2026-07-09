const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

async function loadShouldShowInstallCard() {
  const modulePath = path.join(__dirname, "..", "dashboard", "src", "lib", "install-status.js");
  const mod = await import(pathToFileURL(modulePath).href);
  return mod.shouldShowInstallCard;
}

test("active token hides install card when activeDays is zero", async () => {
  const shouldShowInstallCard = await loadShouldShowInstallCard();
  const actual = shouldShowInstallCard({
    publicMode: false,
    screenshotMode: false,
    forceInstall: false,
    accessEnabled: true,
    heatmapLoading: false,
    activeDays: 0,
    hasActiveDeviceToken: true,
  });
  assert.equal(actual, false);
});

test("forceInstall shows install card even with active token", async () => {
  const shouldShowInstallCard = await loadShouldShowInstallCard();
  const actual = shouldShowInstallCard({
    publicMode: false,
    screenshotMode: false,
    forceInstall: true,
    accessEnabled: true,
    heatmapLoading: false,
    activeDays: 0,
    hasActiveDeviceToken: true,
  });
  assert.equal(actual, true);
});
