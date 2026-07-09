import React, { useLayoutEffect, useRef } from "react";
import { gsap } from "./gsap.js";

const CHIP_KEYS = ["p1", "p2", "p3"];

function segmentTitle(title) {
  if (typeof Intl !== "undefined" && Intl.Segmenter) {
    const segmenter = new Intl.Segmenter(undefined, { granularity: "word" });
    return Array.from(segmenter.segment(title), ({ segment, isWordLike }) => ({
      text: segment,
      isWordLike: Boolean(isWordLike ?? segment.trim()),
    }));
  }
  if (title.includes(" ")) {
    return title.split(/(\s+)/).map((segment) => ({
      text: segment,
      isWordLike: Boolean(segment.trim()),
    }));
  }
  return Array.from(title).map((segment) => ({
    text: segment,
    isWordLike: /[\p{L}\p{N}]/u.test(segment),
  }));
}

/**
 * Local-first manifesto: a near-empty, typography-led statement. The headline
 * reveals word by word as it scrolls into view; the last two words carry the
 * purple gradient.
 */
export function PrivacySection({ copy, animate }) {
  const sectionRef = useRef(null);
  const title = copy("landing.v3.privacy.title");
  const segments = segmentTitle(title);
  const highlightStart = Math.max(
    0,
    segments.filter((segment) => segment.isWordLike).length - 2,
  );
  let wordIndex = 0;

  useLayoutEffect(() => {
    if (!animate) return undefined;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".lv3-privacy-word",
        { autoAlpha: 0, y: 26, rotateX: -35 },
        {
          autoAlpha: 1,
          y: 0,
          rotateX: 0,
          duration: 0.7,
          stagger: 0.07,
          ease: "power3.out",
          scrollTrigger: { trigger: sectionRef.current, start: "top 68%" },
        },
      );
      gsap.fromTo(
        ".lv3-privacy-chip",
        { autoAlpha: 0, y: 14 },
        {
          autoAlpha: 1,
          y: 0,
          duration: 0.5,
          stagger: 0.1,
          delay: 0.4,
          ease: "power2.out",
          scrollTrigger: { trigger: sectionRef.current, start: "top 68%" },
        },
      );
    }, sectionRef);
    return () => ctx.revert();
  }, [animate, title]);

  return (
    <section
      ref={sectionRef}
      className="relative overflow-hidden border-t border-oai-gray-900 py-24 sm:py-32 lg:py-44"
      style={{ background: "radial-gradient(60rem 30rem at 50% 120%, var(--lv3-accent-ghost), transparent 70%)" }}
    >
      <div className="mx-auto max-w-4xl px-4 text-center sm:px-6" style={{ perspective: "900px" }}>
        <p className="text-xs font-bold uppercase tracking-[0.3em] text-[color:var(--lv3-accent-soft)]">
          {copy("landing.v3.privacy.kicker")}
        </p>
        <h2 className="mt-6 text-balance text-4xl font-semibold leading-[1.12] tracking-tight text-white sm:text-5xl lg:text-6xl">
          {segments.map((segment, i) => {
            const currentWordIndex = segment.isWordLike ? wordIndex++ : -1;
            return (
              <span key={i} className="lv3-privacy-word inline-block whitespace-pre">
                <span
                  className={
                    segment.isWordLike && currentWordIndex >= highlightStart
                      ? "bg-gradient-to-b from-[color:var(--lv3-accent-soft)] to-[color:var(--lv3-accent)] bg-clip-text text-transparent"
                      : undefined
                  }
                >
                  {segment.text}
                </span>
              </span>
            );
          })}
        </h2>
        <p className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-oai-gray-400">
          {copy("landing.v2.distill.body")}
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          {CHIP_KEYS.map((key) => (
            <span
              key={key}
              className="lv3-privacy-chip inline-flex items-center gap-2 rounded-full border border-oai-gray-800 bg-oai-black px-4 py-2 font-mono text-[11px] uppercase tracking-widest text-oai-gray-300"
            >
              <span className="h-1 w-1 rounded-full bg-[color:var(--lv3-accent)]" aria-hidden="true" />
              {copy(`landing.v3.privacy.${key}`)}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
