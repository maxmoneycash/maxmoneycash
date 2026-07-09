import React, { useRef, useState } from "react";
import { cn } from "../../../lib/cn";

export function SpotlightCard({
  children,
  className = "",
  spotlightColor = "rgba(138, 122, 255, 0.12)",
  ...props
}) {
  const containerRef = useRef(null);
  const [coords, setCoords] = useState({ x: 0, y: 0 });
  const [isFocused, setIsFocused] = useState(false);

  const handlePointerMove = (e) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setCoords({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };

  return (
    <div
      ref={containerRef}
      onPointerMove={handlePointerMove}
      onPointerEnter={() => setIsFocused(true)}
      onPointerLeave={() => setIsFocused(false)}
      className={cn(
        "relative overflow-hidden rounded-xl border border-oai-gray-800 bg-[#080808] p-5 shadow-2xl transition-all duration-300",
        className
      )}
      {...props}
    >
      {/* Spotlight Halo Overlay */}
      <div
        className="pointer-events-none absolute -inset-px rounded-xl opacity-0 transition-opacity duration-300 z-0"
        style={{
          opacity: isFocused ? 1 : 0,
          background: `radial-gradient(350px circle at ${coords.x}px ${coords.y}px, ${spotlightColor}, transparent 80%)`,
        }}
      />
      <div className="relative z-10 w-full h-full">{children}</div>
    </div>
  );
}

export default SpotlightCard;
