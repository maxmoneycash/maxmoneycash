import React from "react";
import { cn } from "../lib/cn";
import {
  LB_STICKY_TH_RANK,
  LB_STICKY_TH_USER,
  LEADERBOARD_TOKEN_COLUMNS,
  lbStickyTdRank,
  lbStickyTdUser,
} from "../lib/leaderboard-columns.js";

function Bone({ className }) {
  return (
    <div
      className={cn(
        "rounded bg-oai-gray-200/70 dark:bg-oai-gray-800/70 animate-pulse",
        className,
      )}
    />
  );
}

function SkeletonRow({ index }) {
  // First 3 rows slightly wider to mimic top-ranked users with longer names/numbers
  const nameW = index < 3 ? "w-24" : index < 8 ? "w-20" : "w-16";
  const totalW = index < 3 ? "w-16" : "w-12";
  const cellW = index < 5 ? "w-14" : "w-10";

  return (
    <tr className="group">
      {/* Rank */}
      <td
        className={cn(
          lbStickyTdRank(false),
          "!group-hover:bg-transparent",
        )}
      >
        <Bone className="h-4 w-6" />
      </td>
      {/* User: avatar + name */}
      <td
        className={cn(
          lbStickyTdUser(false),
          "!group-hover:bg-transparent",
        )}
      >
        <div className="flex items-center gap-4">
          <Bone className="h-8 w-8 min-w-8 rounded-full" />
          <Bone className={cn("h-4", nameW)} />
        </div>
      </td>
      {/* Total */}
      <td className="px-4 py-4 bg-white dark:bg-oai-gray-950">
        <Bone className={cn("h-4", totalW)} />
      </td>
      {/* Cost */}
      <td className="px-4 py-4 bg-white dark:bg-oai-gray-950">
        <Bone className="h-4 w-12" />
      </td>
      {/* Provider columns */}
      {LEADERBOARD_TOKEN_COLUMNS.map((col) => (
        <td key={col.key} className="px-4 py-4 bg-white dark:bg-oai-gray-950">
          <Bone className={cn("h-4", cellW)} />
        </td>
      ))}
    </tr>
  );
}

/**
 * Skeleton loader that mirrors the leaderboard table structure.
 * Renders `rows` shimmer rows with the same sticky columns and cell layout.
 */
export function LeaderboardSkeleton({ rows = 10 }) {
  return (
    <div className="w-full overflow-x-auto">
      <table className="min-w-max w-full text-left text-sm">
        <thead className="border-b border-oai-gray-200 dark:border-oai-gray-800">
          <tr>
            <th
              className={cn(
                LB_STICKY_TH_RANK,
                "font-medium text-oai-gray-500 dark:text-oai-gray-400",
              )}
            >
              <Bone className="h-3.5 w-6" />
            </th>
            <th
              className={cn(
                LB_STICKY_TH_USER,
                "font-medium text-oai-gray-500 dark:text-oai-gray-400",
              )}
            >
              <Bone className="h-3.5 w-12" />
            </th>
            <th className="px-4 py-4">
              <Bone className="h-3.5 w-10" />
            </th>
            <th className="px-4 py-4">
              <Bone className="h-3.5 w-14" />
            </th>
            {LEADERBOARD_TOKEN_COLUMNS.map((col) => (
              <th key={col.key} className="px-4 py-4">
                <Bone className="h-3.5 w-12" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-oai-gray-100 dark:divide-oai-gray-800/50">
          {Array.from({ length: rows }, (_, i) => (
            <SkeletonRow key={i} index={i} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
