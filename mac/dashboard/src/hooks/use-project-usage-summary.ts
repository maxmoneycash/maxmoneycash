import { useCallback, useEffect, useState } from "react";
import { isAccessTokenReady, resolveAuthAccessToken } from "../lib/auth-token";
import { isMockEnabled } from "../lib/mock-data";
import { getProjectUsageSummary } from "../lib/api";

export function useProjectUsageSummary({
  baseUrl,
  accessToken,
  limit = 3,
  from,
  to,
  source,
  timeZone,
  tzOffsetMinutes,
}: any = {}) {
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mockEnabled = isMockEnabled();
  const tokenReady = isAccessTokenReady(accessToken);

  const isLocalMode = typeof window !== "undefined" &&
    (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1");

  const refresh = useCallback(async () => {
    const resolvedToken = await resolveAuthAccessToken(accessToken);
    // 本地模式允许空 token
    if (!resolvedToken && !mockEnabled && !isLocalMode) {
      setEntries([]);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await getProjectUsageSummary({
        baseUrl,
        accessToken: resolvedToken,
        limit,
        from,
        to,
        source,
        timeZone,
        tzOffsetMinutes,
      });
      setEntries(Array.isArray(res?.entries) ? res.entries : []);
    } catch (err) {
      const message = (err as any)?.message || String(err);
      setError(message);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [accessToken, baseUrl, from, limit, mockEnabled, source, timeZone, to, tzOffsetMinutes, isLocalMode]);

  useEffect(() => {
    // 本地模式跳过 token 检查
    if (!tokenReady && !mockEnabled && !isLocalMode) {
      setEntries([]);
      setError(null);
      setLoading(false);
      return;
    }
    refresh();
  }, [mockEnabled, refresh, tokenReady, isLocalMode]);

  return { entries, loading, error, refresh };
}
