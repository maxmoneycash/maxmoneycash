import { describe, expect, it } from "vitest";
import {
  computeZoomStats,
  formatBucketRange,
  formatTickLabel,
  getTrendInsightKey,
  granularityFromPeriod,
} from "./trend-stats";

describe("granularityFromPeriod", () => {
  it("maps period to trend granularity (mirrors use-trend-data mode)", () => {
    expect(granularityFromPeriod("day")).toBe("hourly");
    expect(granularityFromPeriod("total")).toBe("monthly");
    expect(granularityFromPeriod("week")).toBe("daily");
    expect(granularityFromPeriod("month")).toBe("daily");
    expect(granularityFromPeriod("custom")).toBe("daily");
  });
});

describe("computeZoomStats", () => {
  it("sums tokens / billable / conversations / cost over observed buckets", () => {
    const rows = [
      { day: "2026-05-01", total_tokens: 100, billable_total_tokens: 80, total_cost_usd: 1, conversation_count: 2 },
      { day: "2026-05-02", total_tokens: 300, billable_total_tokens: 200, total_cost_usd: 3, conversation_count: 5 },
    ];
    const s = computeZoomStats(rows);
    expect(s.totalTokens).toBe(400);
    expect(s.billableTokens).toBe(280);
    expect(s.totalCostUsd).toBe(4);
    expect(s.conversationCount).toBe(7);
    expect(s.bucketCount).toBe(2);
    expect(s.activeBuckets).toBe(2);
    expect(s.peak).toEqual({ value: 200, label: "2026-05-02" });
  });

  it("returns null cost when no row carries cost data (avoid misleading $0)", () => {
    const rows = [{ day: "2026-05-01", total_tokens: 100, billable_total_tokens: 100 }];
    expect(computeZoomStats(rows).totalCostUsd).toBeNull();
  });

  it("ignores missing/future rows", () => {
    const rows = [
      { day: "2026-05-01", total_tokens: 100, billable_total_tokens: 100, total_cost_usd: 1 },
      { day: "2026-05-02", missing: true, total_tokens: 999 },
      { day: "2026-05-03", future: true, total_tokens: 999 },
    ];
    const s = computeZoomStats(rows);
    expect(s.totalTokens).toBe(100);
    expect(s.bucketCount).toBe(1);
    expect(s.totalCostUsd).toBe(1);
  });

  it("handles empty / non-array input", () => {
    expect(computeZoomStats([]).totalTokens).toBe(0);
    expect(computeZoomStats(null).peak).toBeNull();
    expect(computeZoomStats(undefined).totalCostUsd).toBeNull();
  });
});

describe("formatBucketRange", () => {
  it("hourly -> 30-min range with end = start + 30min", () => {
    expect(formatBucketRange({ hour: "2026-05-29T14:00:00" }, "hourly")).toBe("2026-05-29 14:00–14:30");
    expect(formatBucketRange({ hour: "2026-05-29T14:30:00" }, "hourly")).toBe("2026-05-29 14:30–15:00");
  });

  it("hourly wraps 23:30 end to 00:00", () => {
    expect(formatBucketRange({ hour: "2026-05-29T23:30:00" }, "hourly")).toBe("2026-05-29 23:30–00:00");
  });

  it("daily and monthly pass through the bucket key", () => {
    expect(formatBucketRange({ day: "2026-05-29" }, "daily")).toBe("2026-05-29");
    expect(formatBucketRange({ month: "2026-05" }, "monthly")).toBe("2026-05");
  });

  it("falls back to raw label for unparseable / missing input", () => {
    expect(formatBucketRange({ hour: "garbage" }, "hourly")).toBe("garbage");
    expect(formatBucketRange(null, "hourly")).toBe("");
  });
});

describe("getTrendInsightKey", () => {
  it("returns the empty key when no buckets are active", () => {
    expect(getTrendInsightKey({ activeBuckets: 0 })).toBe("trend.zoom.insight.empty");
    expect(getTrendInsightKey(null)).toBe("trend.zoom.insight.empty");
  });

  it("tiers the insight by total volume", () => {
    expect(getTrendInsightKey({ activeBuckets: 3, totalTokens: 5_000_000 })).toBe("trend.zoom.insight.calm");
    expect(getTrendInsightKey({ activeBuckets: 3, totalTokens: 100_000_000 })).toBe("trend.zoom.insight.steady");
    expect(getTrendInsightKey({ activeBuckets: 3, totalTokens: 1_000_000_000 })).toBe("trend.zoom.insight.heavy");
    expect(getTrendInsightKey({ activeBuckets: 3, totalTokens: 10_000_000_000 })).toBe("trend.zoom.insight.massive");
  });
});

describe("formatTickLabel", () => {
  it("emits short labels per granularity", () => {
    expect(formatTickLabel({ hour: "2026-05-29T14:30:00" }, "hourly")).toBe("14:30");
    expect(formatTickLabel({ day: "2026-05-29" }, "daily")).toBe("05-29");
    expect(formatTickLabel({ month: "2026-05" }, "monthly")).toBe("2026-05");
  });

  it("returns empty string for null row", () => {
    expect(formatTickLabel(null, "daily")).toBe("");
  });
});
