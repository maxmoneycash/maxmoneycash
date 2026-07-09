import { useEffect, useState } from "react";
import { getLeaderboard, getCommunityModels } from "../lib/api";

const FETCH_TIMEOUT_MS = 6000;
// One page of 100 gives a strong lower bound on the global total without a
// dedicated stats endpoint (the leaderboard is heavily top-weighted).
const SAMPLE_LIMIT = 100;

function withTimeout(promise, ms) {
  let timeoutId;
  const timeout = new Promise((_resolve, reject) => {
    timeoutId = setTimeout(() => reject(new Error("landing stats timeout")), ms);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timeoutId != null) clearTimeout(timeoutId);
  });
}

// The stats are global and slow-moving, but the hook mounts on both the
// landing page and the leaderboard — share one in-flight/recent fetch so an
// SPA navigation between them doesn't refire the identical request pair.
const CACHE_TTL_MS = 60_000;
let cachedFetch = null;

function fetchCommunityData() {
  if (cachedFetch && Date.now() - cachedFetch.at < CACHE_TTL_MS) {
    return cachedFetch.promise;
  }
  const promise = Promise.all([
    getLeaderboard({ period: "total", limit: SAMPLE_LIMIT, offset: 0 }),
    getCommunityModels().catch(() => null),
  ]);
  cachedFetch = { at: Date.now(), promise };
  // Never cache a failure: the next consumer should retry.
  promise.catch(() => {
    if (cachedFetch?.promise === promise) cachedFetch = null;
  });
  return promise;
}

export function resetCommunityStatsCacheForTests() {
  cachedFetch = null;
}

/**
 * Fetches the public leaderboard once (idle-time, anonymous) and derives the
 * community's live numbers: a floor for total tokens synced, the number of
 * syncing developers, and the top-3 podium slice. Also fetches real
 * model-level token breakdown from the community-models endpoint.
 * Never throws: on any failure `status` becomes "error" and consumers
 * fall back to static copy.
 */
export function useCommunityStats({ enabled = true } = {}) {
  const [state, setState] = useState({
    status: "loading",
    tokenFloor: null,
    totalEntries: null,
    top: [],
  });

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let idleId = null;
    let timerId = null;

    const run = async () => {
      try {
        // Fetch leaderboard + model breakdown in parallel.
        // Model breakdown is best-effort: if it fails we still show
        // provider-level data from the snapshot.
        const [data, modelsData] = await withTimeout(
          fetchCommunityData(),
          FETCH_TIMEOUT_MS,
        );
        if (cancelled) return;
        const entries = Array.isArray(data?.entries) ? data.entries : [];
        const sampledTokenFloor = entries.reduce(
          (sum, entry) => sum + (Number(entry?.total_tokens) || 0),
          0,
        );
        const communityTotalTokens = Number(modelsData?.total_tokens) || 0;
        const tokenFloor = communityTotalTokens > 0 ? communityTotalTokens : sampledTokenFloor;
        if (!entries.length || !(tokenFloor > 0)) {
          setState((prev) => ({ ...prev, status: "error" }));
          return;
        }

        // Real model-level breakdown from the dedicated endpoint
        const topModels = Array.isArray(modelsData?.top_models) ? modelsData.top_models : [];

        setState({
          status: "ready",
          tokenFloor,
          totalEntries: Number(data?.total_entries) || entries.length,
          top: entries.slice(0, 3),
          topModels,
        });
      } catch (_e) {
        // Public stats are decorative: fall back to static copy silently.
        if (!cancelled) setState((prev) => ({ ...prev, status: "error" }));
      }
    };

    // Idle-time so the fetch never competes with first paint / LCP.
    if (typeof window !== "undefined" && "requestIdleCallback" in window) {
      idleId = window.requestIdleCallback(run, { timeout: 1500 });
    } else {
      timerId = setTimeout(run, 400);
    }

    return () => {
      cancelled = true;
      if (idleId != null && typeof window.cancelIdleCallback === "function") {
        window.cancelIdleCallback(idleId);
      }
      if (timerId != null) clearTimeout(timerId);
    };
  }, [enabled]);

  return state;
}
