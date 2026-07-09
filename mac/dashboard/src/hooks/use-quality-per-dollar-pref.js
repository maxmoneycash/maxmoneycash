import { useCallback, useEffect, useState } from "react";

// Opt-in toggle for the quality-per-dollar / Effective-Tokens card.
// Default OFF. Persisted under the existing `tt.*` localStorage namespace so it
// sits alongside tt.limits.* etc. The card renders only when this is on AND the
// outcomes sidecar actually has data, so flipping it on with no data shows
// nothing new. See GitHub issue 229.
export const QUALITY_PER_DOLLAR_PREF_KEY = "tt.qualityPerDollar.enabled";

function readEnabled() {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(QUALITY_PER_DOLLAR_PREF_KEY) === "1";
  } catch {
    return false;
  }
}

export function useQualityPerDollarPref() {
  const [enabled, setEnabledState] = useState(readEnabled);

  // Cross-tab + same-tab sync via the storage event.
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onStorage = (e) => {
      if (e.key === null || e.key === QUALITY_PER_DOLLAR_PREF_KEY) {
        setEnabledState(readEnabled());
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setEnabled = useCallback((next) => {
    const value = Boolean(next);
    setEnabledState(value);
    try {
      window.localStorage.setItem(QUALITY_PER_DOLLAR_PREF_KEY, value ? "1" : "0");
    } catch {
      // ignore write failures (private mode, quota, …)
    }
  }, []);

  const toggle = useCallback(() => setEnabled(!readEnabled()), [setEnabled]);

  return { enabled, setEnabled, toggle };
}
