/**
 * Best-effort client-side OS detection for tailoring the landing page download
 * CTA ("Download for macOS" vs "Download for Windows"). Coarse on purpose — we
 * only branch on mac / windows / everything-else, and always keep an "other
 * platforms" escape hatch, so a wrong guess never blocks a download.
 *
 * SSR/build-safe: returns "other" when there is no navigator (e.g. during the
 * Vite build's module evaluation).
 */
export type DetectedOS = "mac" | "windows" | "other";

export function detectOS(): DetectedOS {
  if (typeof navigator === "undefined") return "other";

  // userAgentData.platform is the modern, spoof-resistant signal; fall back to
  // the legacy userAgent / platform strings which still cover every browser.
  const uaDataPlatform =
    (navigator as Navigator & { userAgentData?: { platform?: string } })
      .userAgentData?.platform ?? "";
  const haystack = `${uaDataPlatform} ${navigator.userAgent ?? ""} ${
    navigator.platform ?? ""
  }`.toLowerCase();

  // Check Windows before Mac: some Windows UA strings contain "like Mac".
  if (haystack.includes("win")) return "windows";
  // "mac" covers macOS; iPhone/iPad are excluded — they can't run the app.
  if (haystack.includes("mac") && !haystack.includes("iphone") && !haystack.includes("ipad")) {
    return "mac";
  }
  return "other";
}
