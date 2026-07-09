import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getCommunityModels, getLeaderboard } from "../lib/api";
import { resetCommunityStatsCacheForTests, useCommunityStats } from "./use-community-stats";

vi.mock("../lib/api", () => ({
  getLeaderboard: vi.fn(),
  getCommunityModels: vi.fn(),
}));

describe("useCommunityStats", () => {
  beforeEach(() => {
    resetCommunityStatsCacheForTests();
    vi.mocked(getLeaderboard).mockReset();
    vi.mocked(getCommunityModels).mockReset();
    window.requestIdleCallback = (callback) => {
      callback();
      return 1;
    };
    window.cancelIdleCallback = vi.fn();
  });

  it("uses the community model aggregate total instead of the leaderboard sample sum", async () => {
    vi.mocked(getLeaderboard).mockResolvedValue({
      total_entries: 600,
      entries: [
        { total_tokens: 100, claude_tokens: 60, gpt_tokens: 40 },
        { total_tokens: 50, claude_tokens: 10, gpt_tokens: 40 },
      ],
    });
    vi.mocked(getCommunityModels).mockResolvedValue({
      total_tokens: 1000,
      top_models: [{ name: "claude-sonnet-4-6", tokens: 700, share: 70 }],
    });

    const { result } = renderHook(() => useCommunityStats());

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.tokenFloor).toBe(1000);
    expect(result.current.totalEntries).toBe(600);
  });

  it("falls back to the leaderboard sample floor when the aggregate total is unavailable", async () => {
    vi.mocked(getLeaderboard).mockResolvedValue({
      total_entries: 2,
      entries: [
        { total_tokens: 100, claude_tokens: 60, gpt_tokens: 40 },
        { total_tokens: 50, claude_tokens: 10, gpt_tokens: 40 },
      ],
    });
    vi.mocked(getCommunityModels).mockResolvedValue({ top_models: [] });

    const { result } = renderHook(() => useCommunityStats());

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.tokenFloor).toBe(150);
  });
});
