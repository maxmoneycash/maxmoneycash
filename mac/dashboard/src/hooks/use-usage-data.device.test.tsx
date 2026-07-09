import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchCloudUsageDaily, fetchCloudUsageSummary } from "../lib/api";
import { useUsageData } from "./use-usage-data";

vi.mock("../lib/api", () => ({
  fetchCloudUsageDaily: vi.fn(async () => ({ from: "2026-06-01", to: "2026-06-30", data: [] })),
  fetchCloudUsageSummary: vi.fn(async () => ({ totals: { total_tokens: 0 }, rolling: null })),
  getUsageDaily: vi.fn(async () => ({ data: [] })),
  getUsageSummary: vi.fn(async () => ({ totals: {} })),
}));
vi.mock("../lib/auth-token", () => ({
  isAccessTokenReady: () => true,
  resolveAuthAccessToken: async (t: any) => t || "test-token",
}));
vi.mock("../lib/mock-data", () => ({ isMockEnabled: () => false }));

describe("useUsageData device scope", () => {
  beforeEach(() => {
    vi.mocked(fetchCloudUsageDaily).mockClear();
    vi.mocked(fetchCloudUsageSummary).mockClear();
    try { window.localStorage.clear(); } catch { /* ignore */ }
  });

  it("forwards deviceId to the cloud daily fetcher", async () => {
    renderHook(() =>
      useUsageData({
        baseUrl: "https://app.tokentracker.cc",
        from: "2026-06-01",
        to: "2026-06-30",
        includeDaily: true,
        cacheKey: "u1",
        timeZone: "UTC",
        accountView: true,
        accountAccessToken: "jwt-token",
        deviceId: "dev-7",
      }),
    );
    await waitFor(() => expect(fetchCloudUsageDaily).toHaveBeenCalled());
    expect(vi.mocked(fetchCloudUsageDaily).mock.calls[0][0]).toMatchObject({ device: "dev-7" });
  });

  it("writes a device-scoped cache key (no collision with all-devices)", async () => {
    renderHook(() =>
      useUsageData({
        baseUrl: "https://app.tokentracker.cc",
        from: "2026-06-01", to: "2026-06-30", includeDaily: false,
        cacheKey: "u1", timeZone: "UTC",
        accountView: true, accountAccessToken: "jwt-token", deviceId: "dev-7",
      }),
    );
    await waitFor(() => expect(fetchCloudUsageSummary).toHaveBeenCalled());
    const keys = Object.keys(window.localStorage);
    expect(keys.some((k) => k.includes("dev-7"))).toBe(true);
  });
});
