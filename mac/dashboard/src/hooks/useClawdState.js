import { useMemo } from "react";

/**
 * Resolves the appropriate Clawd animation state based on dashboard data.
 *
 * Priority chain (high → low):
 * 1. Status overrides: error > disconnected
 * 2. Syncing activity
 * 3. Token volume tiers
 *
 * @param {object} opts
 * @param {number} opts.todayTokens - Today's total token count
 * @param {boolean} opts.isSyncing - Whether data is currently syncing
 * @param {boolean} opts.hasError - Whether there's an error state
 * @param {boolean} opts.isDisconnected - Whether server is disconnected
 * @returns {string} Clawd animation state name
 */
export function useClawdState({
  todayTokens = 0,
  isSyncing = false,
  hasError = false,
  isDisconnected = false,
} = {}) {
  return useMemo(() => {
    // 1. Status overrides
    if (hasError) return "error";
    if (isDisconnected) return "disconnected";

    // 2. Syncing
    if (isSyncing) return "working-typing";

    // 3. Token volume tiers
    if (todayTokens === 0) return "sleeping";
    if (todayTokens < 50_000) return "idle-living";
    if (todayTokens < 200_000) return "idle-look";
    if (todayTokens < 500_000) return "working-ultrathink";
    if (todayTokens < 2_000_000) return "working-typing";
    return "working-ultrathink";
  }, [todayTokens, isSyncing, hasError, isDisconnected]);
}
