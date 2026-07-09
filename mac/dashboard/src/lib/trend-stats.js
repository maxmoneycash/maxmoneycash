// Pure helpers for the Usage Trend zoom view. Kept dependency-free and in a
// standalone module so both TrendMonitor.jsx and TrendMonitorZoomModal.jsx can
// import them without creating a component<->modal import cycle.

// Map the dashboard `period` to the trend granularity (mirrors the `mode`
// derivation in use-trend-data.ts: day -> hourly, total -> monthly, else daily).
export function granularityFromPeriod(period) {
  if (period === "day") return "hourly";
  if (period === "total") return "monthly";
  return "daily";
}

// True only for observed buckets — missing/future rows are previews, not data.
function isObserved(row) {
  return !!row && !row.missing && !row.future;
}

// Numeric tokens for a row, preferring the billable figure used for cost.
function rowBillable(row) {
  const raw = row?.billable_total_tokens ?? row?.total_tokens ?? row?.value;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

function rowTotal(row) {
  const raw = row?.total_tokens ?? row?.billable_total_tokens ?? row?.value;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

// Aggregate stats over the observed buckets of a trend series. Cost is null when
// no row carries cost data, so callers can hide the row instead of rendering a
// misleading $0.00.
export function computeZoomStats(rows) {
  const list = Array.isArray(rows) ? rows.filter(isObserved) : [];

  let totalTokens = 0;
  let billableTokens = 0;
  let conversationCount = 0;
  let costSum = 0;
  let anyCost = false;
  let activeBuckets = 0;
  let peakValue = -1;
  let peakRow = null;

  for (const row of list) {
    const total = rowTotal(row);
    const billable = rowBillable(row);
    totalTokens += total;
    billableTokens += billable;

    const conv = Number(row?.conversation_count);
    if (Number.isFinite(conv) && conv > 0) conversationCount += conv;

    const cost = Number(row?.total_cost_usd);
    if (Number.isFinite(cost)) {
      anyCost = true;
      costSum += cost;
    }

    if (billable > 0) activeBuckets += 1;
    if (billable > peakValue) {
      peakValue = billable;
      peakRow = row;
    }
  }

  return {
    totalTokens,
    billableTokens,
    conversationCount,
    totalCostUsd: anyCost ? costSum : null,
    bucketCount: list.length,
    activeBuckets,
    peak: peakRow && peakValue > 0
      ? { value: peakValue, label: peakRow.hour || peakRow.day || peakRow.month || "" }
      : null,
  };
}

// Pad "1" -> "01".
function pad2(n) {
  return String(n).padStart(2, "0");
}

// Precise time RANGE label for a hovered bucket, by granularity:
//   hourly  "YYYY-MM-DDTHH:MM:00" -> "YYYY-MM-DD HH:MM–HH:MM" (end = start + 30min)
//   daily   "YYYY-MM-DD"          -> "YYYY-MM-DD"
//   monthly "YYYY-MM"             -> "YYYY-MM"
// Falls back to the raw label (or "") for anything unparseable.
export function formatBucketRange(row, granularity) {
  if (!row) return "";

  if (granularity === "hourly") {
    const raw = String(row.hour || row.label || "");
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/.exec(raw);
    if (!m) return raw;
    const [, date, hh, mm] = m;
    const startMinutes = Number(hh) * 60 + Number(mm);
    const endMinutes = startMinutes + 30;
    const endH = Math.floor(endMinutes / 60) % 24;
    const endM = endMinutes % 60;
    return `${date} ${hh}:${mm}–${pad2(endH)}:${pad2(endM)}`;
  }

  if (granularity === "monthly") {
    return String(row.month || row.label || "");
  }

  // daily
  return String(row.day || row.label || "");
}

// One-line insight copy key for the zoom stats panel, tiered by total volume so
// the line reads like a character note rather than a number it just restated.
// The caller passes formatted params to copy(): { active, peak }.
export function getTrendInsightKey(stats) {
  if (!stats || stats.activeBuckets === 0) return "trend.zoom.insight.empty";
  const total = stats.totalTokens || 0;
  if (total < 10_000_000) return "trend.zoom.insight.calm";
  if (total < 500_000_000) return "trend.zoom.insight.steady";
  if (total < 5_000_000_000) return "trend.zoom.insight.heavy";
  return "trend.zoom.insight.massive";
}

// Short axis-tick label for a bucket (no date noise):
//   hourly  -> "HH:MM"   daily -> "MM-DD"   monthly -> "YYYY-MM"
export function formatTickLabel(row, granularity) {
  if (!row) return "";
  if (granularity === "hourly") {
    const m = /T(\d{2}:\d{2})/.exec(String(row.hour || row.label || ""));
    return m ? m[1] : "";
  }
  if (granularity === "monthly") {
    return String(row.month || row.label || "");
  }
  const day = String(row.day || row.label || "");
  const m = /^\d{4}-(\d{2}-\d{2})$/.exec(day);
  return m ? m[1] : day;
}
