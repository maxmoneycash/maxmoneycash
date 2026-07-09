import React, { useLayoutEffect, useRef } from "react";
import { LogoCarousel } from "../LogoCarousel.jsx";
import { AGENT_LOGOS } from "../agent-logos.js";
import { gsap } from "./gsap.js";

export function ToolsStrip({ copy, animate }) {
  const sectionRef = useRef(null);
  const innerRef = useRef(null);

  useLayoutEffect(() => {
    if (!animate) return undefined;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        innerRef.current,
        { autoAlpha: 0, y: 28 },
        {
          autoAlpha: 1,
          y: 0,
          duration: 0.8,
          ease: "power3.out",
          scrollTrigger: { trigger: sectionRef.current, start: "top 85%" },
        },
      );
    }, sectionRef);
    return () => ctx.revert();
  }, [animate]);

  return (
    <section ref={sectionRef} className="relative border-y border-oai-gray-900 bg-oai-gray-950/50 py-12 lg:py-16">
      <div ref={innerRef} className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="flex flex-col justify-between gap-10 md:flex-row md:items-center">
          <div className="shrink-0 md:max-w-[16rem]">
            <p className="text-sm font-semibold uppercase tracking-wider text-oai-gray-400">
              {copy("landing.v2.models.title")}
            </p>
            <p className="mt-2 text-xs leading-relaxed text-oai-gray-500">
              {copy("landing.v3.tools.count", { count: AGENT_LOGOS.length })}
            </p>
          </div>
          <div className="flex justify-center md:justify-end">
            <LogoCarousel logos={AGENT_LOGOS} columnCount={6} />
          </div>
        </div>
      </div>
    </section>
  );
}
