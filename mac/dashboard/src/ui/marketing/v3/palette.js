// Single source of truth for the landing v3 deep-space purple palette.
// Every purple used on the landing page must come from here (as a CSS
// variable set on the page root) so validate:ui-hardcode only ever sees
// hex literals in this one file.
export const LV3 = {
  accent: "#8a7aff",
  accentSoft: "#b8b3ff",
  accentFaint: "rgba(138, 122, 255, 0.16)",
  accentGhost: "rgba(138, 122, 255, 0.06)",
  glint: "#fbdfff",
  bg: "#050507",
  panel: "#0a0a0d",
  line: "rgba(138, 122, 255, 0.22)",
  scrim: "rgba(5, 5, 7, 0.62)",
  // Glass-planet provider orbs. The body stays translucent — a backdrop blur
  // frosts whatever shines behind it (so particles never punch through) —
  // while stacked gradients paint the sphere: diffuse light upper-left,
  // purple bounce-light from the galaxy below, shaded lower body.
  orbSurface:
    "radial-gradient(circle at 30% 24%, rgba(255, 255, 255, 0.34), rgba(255, 255, 255, 0.06) 42%, rgba(255, 255, 255, 0) 55%), radial-gradient(circle at 68% 84%, rgba(138, 122, 255, 0.30), rgba(138, 122, 255, 0) 55%), radial-gradient(circle at 50% 50%, rgba(20, 18, 34, 0.55), rgba(8, 8, 16, 0.82) 78%)",
  orbShadow:
    "inset 0 1px 1px rgba(255, 255, 255, 0.30), inset 0 -3px 9px rgba(138, 122, 255, 0.38), inset -5px -7px 14px rgba(0, 0, 0, 0.38), 0 0 30px rgba(138, 122, 255, 0.20), 0 10px 26px rgba(0, 0, 0, 0.5)",
  orbHighlight: "linear-gradient(to bottom, rgba(255, 255, 255, 0.5), rgba(255, 255, 255, 0))",
  orbGlint: "radial-gradient(circle, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0) 70%)",
};

// Numeric variants for three.js (never trip COLOR_REGEX).
export const LV3_GL = {
  accent: 0x8a7aff,
  accentSoft: 0xb8b3ff,
  glint: 0xfbdfff,
};

// CSS custom properties applied on the landing root element.
export const LV3_CSS_VARS = {
  "--lv3-accent": LV3.accent,
  "--lv3-accent-soft": LV3.accentSoft,
  "--lv3-accent-faint": LV3.accentFaint,
  "--lv3-accent-ghost": LV3.accentGhost,
  "--lv3-glint": LV3.glint,
  "--lv3-bg": LV3.bg,
  "--lv3-panel": LV3.panel,
  "--lv3-line": LV3.line,
  "--lv3-scrim": LV3.scrim,
  "--lv3-orb-surface": LV3.orbSurface,
  "--lv3-orb-shadow": LV3.orbShadow,
  "--lv3-orb-highlight": LV3.orbHighlight,
  "--lv3-orb-glint": LV3.orbGlint,
};
