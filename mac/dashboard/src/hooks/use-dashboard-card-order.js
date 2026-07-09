import { useCallback } from "react";
import { useOrderedList } from "./use-ordered-list.js";

const LEFT_STORAGE_KEY = "tokentracker.dashboard.leftCardOrder.v1";
const RIGHT_STORAGE_KEY = "tokentracker.dashboard.rightCardOrder.v1";

/**
 * Manage the drag-to-reorder card layout for the Overview page's two
 * independent columns. Each column keeps its own persisted order; there is
 * no shared context between them, so cards can never cross columns.
 */
export function useDashboardCardOrder(leftDefaults, rightDefaults) {
  const left = useOrderedList(LEFT_STORAGE_KEY, leftDefaults);
  const right = useOrderedList(RIGHT_STORAGE_KEY, rightDefaults);

  const isCustomized =
    left.order.join("|") !== leftDefaults.join("|") ||
    right.order.join("|") !== rightDefaults.join("|");

  const resetAll = useCallback(() => {
    left.reset();
    right.reset();
  }, [left, right]);

  return { left, right, isCustomized, resetAll };
}
