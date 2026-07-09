import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAccountDevices } from "../lib/api";
import { useAccountDevices } from "./use-account-devices";

vi.mock("../lib/api", () => ({ fetchAccountDevices: vi.fn() }));
vi.mock("../lib/auth-token", () => ({
  resolveAuthAccessToken: async (t: any) => t || "test-token",
}));

describe("useAccountDevices", () => {
  beforeEach(() => vi.mocked(fetchAccountDevices).mockReset());

  it("returns devices in account view", async () => {
    vi.mocked(fetchAccountDevices).mockResolvedValue({
      from: "2026-06-01", to: "2026-06-30",
      devices: [{ id: "d1", device_name: "MacBook", platform: "darwin", total_tokens: 10 }],
    });
    const { result } = renderHook(() =>
      useAccountDevices({
        from: "2026-06-01", to: "2026-06-30", timeZone: "UTC",
        accountView: true, accountAccessToken: "jwt",
      }),
    );
    await waitFor(() => expect(result.current.devices).toHaveLength(1));
    expect(result.current.devices[0]).toMatchObject({ id: "d1", device_name: "MacBook" });
  });

  it("returns empty and does not fetch outside account view", async () => {
    const { result } = renderHook(() =>
      useAccountDevices({ from: "2026-06-01", to: "2026-06-30", accountView: false, accountAccessToken: null }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.devices).toEqual([]);
    expect(fetchAccountDevices).not.toHaveBeenCalled();
  });
});
