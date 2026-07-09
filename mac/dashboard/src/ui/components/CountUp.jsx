import React, { useEffect, useRef, useState } from "react";

const DEFAULT_DURATION_MS = 1800;
// How often the post-count-up live feed commits a React re-render.
const LIVE_COMMIT_MS = 250;

function defaultFormat(value) {
  return Math.round(value).toLocaleString("en-US");
}

/**
 * Animated number that counts from its previously displayed value to `value`
 * the first time it scrolls into view (and again whenever `value` changes,
 * e.g. when live stats replace the static fallback). With `ratePerSec > 0`
 * the digits keep ticking upward after the count-up lands — an estimated
 * live feed, calibrated by the real fetch on load. With `animate === false`
 * it renders the final value immediately and never ticks.
 */
export function CountUp({
  value,
  animate = true,
  durationMs = DEFAULT_DURATION_MS,
  format = defaultFormat,
  ratePerSec = 0,
  className,
}) {
  const target = Number(value) || 0;
  const [display, setDisplay] = useState(animate ? 0 : target);
  const nodeRef = useRef(null);
  const displayRef = useRef(animate ? 0 : target);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    displayRef.current = display;
  }, [display]);

  useEffect(() => {
    if (!animate) return undefined;
    const node = nodeRef.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setInView(true);
      return undefined;
    }
    // Track visibility continuously: leaving the viewport tears down the rAF
    // loop below, so the live ticker never runs for an off-screen counter.
    const io = new IntersectionObserver(
      (entries) => setInView(Boolean(entries[0]?.isIntersecting)),
      { threshold: 0.4 },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [animate]);

  useEffect(() => {
    if (!animate) {
      setDisplay(target);
      return undefined;
    }
    if (!inView) return undefined;
    const from = displayRef.current;
    if (from === target && !(ratePerSec > 0)) return undefined;
    let rafId = 0;
    const start = performance.now();
    let prev = start;
    let lastCommit = 0;
    // Re-entering the viewport after live-ticking past `target` must not
    // replay the count-up (it would ease downward) — jump straight to the feed.
    const skipCountUp = ratePerSec > 0 && from >= target;
    let live = Math.max(from, target);
    const tick = (now) => {
      const t = skipCountUp ? 1 : Math.min(1, (now - start) / durationMs);
      if (t < 1) {
        const eased = 1 - Math.pow(1 - t, 4);
        setDisplay(from + (target - from) * eased);
        prev = now;
        rafId = requestAnimationFrame(tick);
        return;
      }
      if (!(ratePerSec > 0)) {
        setDisplay(target);
        return;
      }
      // Count-up finished — keep ticking at the estimated community rate,
      // accumulating every frame but committing a re-render only a few times
      // per second instead of at 60fps for the lifetime of the page.
      const dt = Math.min(now - prev, 100) / 1000;
      prev = now;
      live = Math.max(live, target) + ratePerSec * dt;
      if (now - lastCommit >= LIVE_COMMIT_MS) {
        lastCommit = now;
        setDisplay(live);
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [animate, inView, target, durationMs, ratePerSec]);

  return (
    <span ref={nodeRef} className={className}>
      {format(display)}
    </span>
  );
}
