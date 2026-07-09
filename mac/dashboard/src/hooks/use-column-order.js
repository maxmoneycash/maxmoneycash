import { useOrderedList } from "./use-ordered-list.js";

const STORAGE_KEY = "tokentracker.leaderboard.columnOrder.v1";

/**
 * Manage an ordered list of column keys with localStorage persistence.
 * Returns stable callbacks and syncs automatically when `defaults` changes.
 */
export function useColumnOrder(defaults) {
  return useOrderedList(STORAGE_KEY, defaults);
}
