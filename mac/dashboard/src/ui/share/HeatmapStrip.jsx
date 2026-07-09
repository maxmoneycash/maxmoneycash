import React from "react";

// Compact 52-week × 7-day activity grid for share cards.
// Call site provides a target `width` (the container width to fill); the
// strip computes cellSize from (width, week count, gap) so it always fits
// exactly — no trailing whitespace, no overflow.

function normalizeLevel(cell) {
  if (!cell || cell.future) return null;
  const raw = typeof cell.level === "number" ? cell.level : 0;
  if (raw < 0) return 0;
  if (raw > 4) return 4;
  return Math.round(raw);
}

export function HeatmapStrip({
  weeks,
  palette,
  width,
  gap = 3,
  radius = 2,
  emptyColor,
}) {
  if (!Array.isArray(weeks) || weeks.length === 0) return null;
  if (!width || width <= 0) return null;

  const innerPalette = palette || ["#eee", "#ccc", "#999", "#666", "#333"];
  const empty = emptyColor || innerPalette[0];
  const count = weeks.length;
  const totalGap = (count - 1) * gap;
  const cellSize = Math.max(4, (width - totalGap) / count);
  const gridHeight = 7 * cellSize + 6 * gap;

  return (
    <svg
      width={width}
      height={gridHeight}
      viewBox={`0 0 ${width} ${gridHeight}`}
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      style={{ display: "block" }}
    >
      {weeks.map((week, wi) => {
        const cells = Array.isArray(week) ? week : [];
        return cells.map((cell, di) => {
          if (di >= 7) return null;
          const level = normalizeLevel(cell);
          const x = wi * (cellSize + gap);
          const y = di * (cellSize + gap);
          const fill = level === null ? empty : innerPalette[level];
          return (
            <rect
              key={`${wi}-${di}`}
              x={x}
              y={y}
              width={cellSize}
              height={cellSize}
              rx={radius}
              ry={radius}
              fill={fill}
            />
          );
        });
      })}
    </svg>
  );
}
