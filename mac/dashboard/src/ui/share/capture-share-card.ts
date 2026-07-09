import { SHARE_CARD_HEIGHT, SHARE_CARD_WIDTH } from "./share-card-constants";
// Note: SHARE_CARD_WIDTH/HEIGHT are kept as fallbacks; actual size is read from the node.

const FONT_CSS_HREF =
  "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter+Tight:wght@400;500;600;700&family=IBM+Plex+Serif:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&family=Space+Grotesk:wght@500;600;700&display=swap";

let fontsInjected = false;

function ensureShareFonts(): void {
  if (typeof document === "undefined") return;
  if (fontsInjected) return;
  const existing = document.querySelector<HTMLLinkElement>(
    'link[data-share-card-fonts="true"]',
  );
  if (existing) {
    fontsInjected = true;
    return;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = FONT_CSS_HREF;
  link.dataset.shareCardFonts = "true";
  link.crossOrigin = "anonymous";
  document.head.appendChild(link);
  fontsInjected = true;
}

async function waitForFonts(): Promise<void> {
  if (typeof document === "undefined") return;
  const fontSet = (document as any).fonts;
  if (!fontSet || typeof fontSet.ready?.then !== "function") return;
  try {
    await fontSet.ready;
  } catch {
    // ignore — we still attempt capture with fallback fonts
  }
}

export interface CaptureOptions {
  pixelRatio?: number;
}

export async function captureShareCard(
  node: HTMLElement,
  options: CaptureOptions = {},
): Promise<Blob | null> {
  if (typeof window === "undefined" || !node) return null;
  ensureShareFonts();
  await waitForFonts();
  // Give the browser one frame so the newly mounted card paints fully.
  await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));

  const { toBlob, toPng } = await import("html-to-image");
  const pixelRatio = options.pixelRatio ?? 2;

  // Read actual size from the node (supports variant-specific dimensions)
  const w = node.offsetWidth || SHARE_CARD_WIDTH;
  const h = node.offsetHeight || SHARE_CARD_HEIGHT;

  const htmlToImageOptions = {
    pixelRatio,
    cacheBust: true,
    width: w,
    height: h,
    style: {
      width: `${w}px`,
      height: `${h}px`,
    },
    skipFonts: false,
    filter: (n: any) =>
      !(n instanceof HTMLElement) || n.dataset?.screenshotExclude !== "true",
  };

  try {
    const blob = await toBlob(node, htmlToImageOptions);
    if (blob) return blob;
  } catch {
    // fall through to PNG data URL path
  }
  try {
    const dataUrl = await toPng(node, htmlToImageOptions);
    if (!dataUrl) return null;
    const res = await fetch(dataUrl);
    return await res.blob();
  } catch {
    return null;
  }
}

export async function blobToPngDataUrl(blob: Blob): Promise<string | null> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : null;
      resolve(result);
    };
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(blob);
  });
}

export function downloadBlobAsFile(blob: Blob, filename: string): boolean {
  if (typeof window === "undefined" || !blob) return false;
  try {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  } catch {
    return false;
  }
}
