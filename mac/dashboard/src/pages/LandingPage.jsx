import React, { useEffect, useMemo, useRef, useState } from "react";
import { copy } from "../lib/copy";
import { safeWriteClipboard } from "../lib/safe-browser";
import { isScreenshotModeEnabled } from "../lib/screenshot-mode";
import { MarketingLanding } from "../ui/marketing/MarketingLanding.jsx";
import { shouldDeferMount } from "./should-defer-mount.js";

function usePrefersReducedMotion() {
  return useMemo(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }, []);
}

function useDeferredMount(delayMs = 0, shouldDefer = true) {
  const [mounted, setMounted] = useState(() => !shouldDefer);

  useEffect(() => {
    if (!shouldDefer) {
      setMounted(true);
      return undefined;
    }
    let timer = null;
    let idleId = null;
    const run = () => setMounted(true);

    if (typeof window !== "undefined" && "requestIdleCallback" in window) {
      idleId = window.requestIdleCallback(run, { timeout: delayMs || 200 });
      return () => {
        if (typeof window.cancelIdleCallback === "function" && idleId != null) {
          window.cancelIdleCallback(idleId);
        }
      };
    }

    timer = window.setTimeout(run, delayMs);
    return () => {
      if (timer != null) window.clearTimeout(timer);
    };
  }, [delayMs, shouldDefer]);

  return mounted;
}

export function LandingPage({ signInUrl, signUpUrl }) {
  const reduceMotion = usePrefersReducedMotion();
  const screenshotMode = useMemo(() => {
    if (typeof window === "undefined") return false;
    return isScreenshotModeEnabled(window.location.search);
  }, []);
  const deferMount = shouldDeferMount({
    prefersReducedMotion: reduceMotion,
    screenshotMode,
  });
  // Heavy WebGL effects mount one idle-frame after first paint so the hero
  // copy (LCP) always renders before the canvas initializes.
  const effectsReady = useDeferredMount(250, deferMount);
  const installEntryKey = "tokentracker.dashboard.from_landing.v1";

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(installEntryKey, "1");
    } catch (_e) {
      // ignore write errors (private mode/quota)
    }
  }, [installEntryKey]);

  const installCommand = copy("landing.install.command");
  const [installCopied, setInstallCopied] = useState(false);
  const installCopiedTimerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (installCopiedTimerRef.current != null) {
        window.clearTimeout(installCopiedTimerRef.current);
      }
    };
  }, []);

  const handleCopyInstall = async () => {
    const didCopy = await safeWriteClipboard(installCommand);
    if (!didCopy) return;
    if (installCopiedTimerRef.current != null) {
      window.clearTimeout(installCopiedTimerRef.current);
    }
    setInstallCopied(true);
    installCopiedTimerRef.current = window.setTimeout(() => {
      setInstallCopied(false);
      installCopiedTimerRef.current = null;
    }, 2000);
  };

  return (
    <MarketingLanding
      copy={copy}
      reduceMotion={reduceMotion}
      screenshotMode={screenshotMode}
      effectsReady={effectsReady}
      signInUrl={signInUrl}
      signUpUrl={signUpUrl}
      installCommand={installCommand}
      installCopied={installCopied}
      onCopyInstallCommand={handleCopyInstall}
    />
  );
}
