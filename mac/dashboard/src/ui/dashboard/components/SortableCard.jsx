import React, { useLayoutEffect, useRef } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { copy } from "../../../lib/copy";
import { cn } from "../../../lib/cn";

/**
 * Wraps a single dashboard card so it can be dragged to reorder within its
 * column. `attributes`/`listeners` are bound only to the small grip handle —
 * never to the card body — so clicks on buttons/inputs/tabs inside the card
 * are never mistaken for a drag.
 *
 * Some cards (WidgetOnboardingCard, QualityPerDollarCard, MacAppBanner, ...)
 * render `null` for their own internal reasons even when their column slot
 * is "visible". A `display:none` sibling still has a zero-size rect that
 * dnd-kit factors into every other item's drag transform, which is exactly
 * what made cards fly off during a drag. So an empty card must not just look
 * collapsed (the `has-[[data-sortable-body]:empty]:hidden` below still
 * covers the first paint) — it must stop being a registered sortable item
 * entirely. `onEmptyChange` reports emptiness up so the parent can drop the
 * id from `SortableContext`'s `items` before the user could ever drag.
 */
export function SortableCard({ id, children, onEmptyChange }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
  });
  const bodyRef = useRef(null);
  const reportedEmptyRef = useRef(null);

  useLayoutEffect(() => {
    if (!onEmptyChange) return;
    const isEmpty = bodyRef.current ? bodyRef.current.childNodes.length === 0 : true;
    if (reportedEmptyRef.current !== isEmpty) {
      reportedEmptyRef.current = isEmpty;
      onEmptyChange(id, isEmpty);
    }
  });

  const style = {
    transform: CSS.Transform.toString(transform) || undefined,
    transition,
    zIndex: isDragging ? 20 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group/sortable relative has-[[data-sortable-body]:empty]:hidden",
        isDragging && "opacity-90",
      )}
    >
      <button
        type="button"
        aria-label={copy("dashboard.overview.layout.drag_handle")}
        className={cn(
          "peer absolute left-1/2 top-1 z-10 flex h-5 w-6 -translate-x-1/2 items-center justify-center rounded-md",
          "cursor-grab active:cursor-grabbing touch-none select-none",
          "text-oai-gray-400 dark:text-oai-gray-600 opacity-0 transition-colors duration-150",
          "hover:text-oai-gray-600 dark:hover:text-oai-gray-300 hover:bg-oai-gray-100 dark:hover:bg-oai-gray-800",
          "group-hover/sortable:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oai-brand/50",
          isDragging && "opacity-100 bg-oai-gray-100 dark:bg-oai-gray-800",
        )}
        {...attributes}
        {...listeners}
      >
        <svg viewBox="0 0 14 8" width="14" height="8" fill="currentColor" aria-hidden="true">
          <circle cx="2" cy="2" r="1" />
          <circle cx="2" cy="6" r="1" />
          <circle cx="7" cy="2" r="1" />
          <circle cx="7" cy="6" r="1" />
          <circle cx="12" cy="2" r="1" />
          <circle cx="12" cy="6" r="1" />
        </svg>
      </button>
      <div
        ref={bodyRef}
        data-sortable-body
        className={cn(
          "rounded-xl transition-shadow duration-200 ease-out",
          "peer-hover:shadow-[0_12px_28px_-14px_rgba(15,23,42,0.22)] dark:peer-hover:shadow-[0_12px_28px_-12px_rgba(0,0,0,0.6)]",
          "peer-focus-visible:shadow-[0_12px_28px_-14px_rgba(15,23,42,0.22)] dark:peer-focus-visible:shadow-[0_12px_28px_-12px_rgba(0,0,0,0.6)]",
          isDragging &&
            "shadow-[0_12px_28px_-14px_rgba(15,23,42,0.22)] dark:shadow-[0_12px_28px_-12px_rgba(0,0,0,0.6)]",
        )}
      >
        {children}
      </div>
    </div>
  );
}
