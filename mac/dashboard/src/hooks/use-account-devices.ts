import { useCallback, useEffect, useState } from "react";
import { resolveAuthAccessToken } from "../lib/auth-token";
import { fetchAccountDevices } from "../lib/api";

/**
 * Lists the signed-in account's active devices with per-device usage totals
 * for [from, to]. Only fetches in account view (cross-device cloud reads);
 * outside it the dashboard is single-device and there is nothing to compare.
 */
export function useAccountDevices({
  from,
  to,
  timeZone,
  tzOffsetMinutes,
  accountView = false,
  accountAccessToken = null,
  accountRevision = 0,
}: any = {}) {
  const enabled = Boolean(accountView && accountAccessToken);
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) {
      setDevices([]);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const token = await resolveAuthAccessToken(accountAccessToken);
      const res = await fetchAccountDevices({ from, to, timeZone, tzOffsetMinutes, accessToken: token });
      setDevices(Array.isArray(res?.devices) ? res.devices : []);
    } catch (e: any) {
      setError(e?.message || String(e));
      setDevices([]);
    } finally {
      setLoading(false);
    }
  }, [enabled, accountAccessToken, from, to, timeZone, tzOffsetMinutes, accountRevision]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { devices, loading, error, refresh };
}
