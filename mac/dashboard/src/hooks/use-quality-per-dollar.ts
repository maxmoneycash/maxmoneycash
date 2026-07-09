import { useCallback, useEffect, useState } from "react";
import { getOutcomes } from "../lib/api";
import { resolveAuthAccessToken } from "../lib/auth-token";

// Fetches the opt-in quality-per-dollar / Effective-Tokens join from the local
// outcomes endpoint. Inert until `enabled` is true, so users who never opt in
// pay no fetch cost. Returns the raw endpoint payload
// ({ available, by_model, by_tool, totals }) plus loading/error.
export function useQualityPerDollar({
  enabled = false,
  from,
  to,
  accessToken,
  deviceId = null,
}: any = {}) {
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const token = await resolveAuthAccessToken(accessToken);
      const res = await getOutcomes({ from, to, device: deviceId, accessToken: token });
      setData(res || null);
    } catch (e: any) {
      setError(e?.message || String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [enabled, from, to, accessToken, deviceId]);

  useEffect(() => {
    if (!enabled) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    refresh();
  }, [enabled, refresh]);

  return { data, loading, error, refresh };
}
