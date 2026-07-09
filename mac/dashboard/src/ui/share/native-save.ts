function isNativeEmbed(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean((window as any)?.webkit?.messageHandlers?.nativeBridge);
}

export interface SaveImageResult {
  ok: boolean;
  path?: string;
  error?: string;
}

export interface CopyImageResult {
  ok: boolean;
  error?: string;
}

const PENDING = new Map<string, (result: SaveImageResult) => void>();
const COPY_PENDING = new Map<string, (result: CopyImageResult) => void>();

function ensureListener(): void {
  if (typeof window === "undefined") return;
  if ((window as any).__tokentrackerNativeSaveListener) return;
  (window as any).__tokentrackerNativeSaveListener = true;
  window.addEventListener("native:saveImageResult", (event: any) => {
    const detail = event?.detail || {};
    const requestId = typeof detail.requestId === "string" ? detail.requestId : null;
    if (!requestId || !PENDING.has(requestId)) return;
    const resolver = PENDING.get(requestId)!;
    PENDING.delete(requestId);
    resolver({
      ok: Boolean(detail.ok),
      path: typeof detail.path === "string" ? detail.path : undefined,
      error: typeof detail.error === "string" ? detail.error : undefined,
    });
  });
  window.addEventListener("native:copyImageResult", (event: any) => {
    const detail = event?.detail || {};
    const requestId = typeof detail.requestId === "string" ? detail.requestId : null;
    if (!requestId || !COPY_PENDING.has(requestId)) return;
    const resolver = COPY_PENDING.get(requestId)!;
    COPY_PENDING.delete(requestId);
    resolver({
      ok: Boolean(detail.ok),
      error: typeof detail.error === "string" ? detail.error : undefined,
    });
  });
}

export async function copyShareImageToClipboard(
  dataUrl: string,
): Promise<CopyImageResult> {
  if (!isNativeEmbed() || typeof window === "undefined") {
    return { ok: false, error: "native bridge unavailable" };
  }
  const handler = (window as any)?.webkit?.messageHandlers?.nativeBridge;
  if (!handler) return { ok: false, error: "native bridge unavailable" };

  ensureListener();
  const requestId = `copy_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(() => {
      if (COPY_PENDING.has(requestId)) {
        COPY_PENDING.delete(requestId);
        resolve({ ok: false, error: "timeout" });
      }
    }, 8000);

    COPY_PENDING.set(requestId, (result) => {
      window.clearTimeout(timeoutId);
      resolve(result);
    });

    try {
      handler.postMessage({
        type: "action",
        name: "copyImageToClipboard",
        requestId,
        dataUrl,
      });
    } catch (error: any) {
      COPY_PENDING.delete(requestId);
      window.clearTimeout(timeoutId);
      resolve({ ok: false, error: error?.message || String(error) });
    }
  });
}

export async function saveShareImageToDownloads(
  dataUrl: string,
  filename: string,
): Promise<SaveImageResult> {
  if (!isNativeEmbed() || typeof window === "undefined") {
    return { ok: false, error: "native bridge unavailable" };
  }
  const handler = (window as any)?.webkit?.messageHandlers?.nativeBridge;
  if (!handler) return { ok: false, error: "native bridge unavailable" };

  ensureListener();
  const requestId = `save_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(() => {
      if (PENDING.has(requestId)) {
        PENDING.delete(requestId);
        resolve({ ok: false, error: "timeout" });
      }
    }, 8000);

    PENDING.set(requestId, (result) => {
      window.clearTimeout(timeoutId);
      resolve(result);
    });

    try {
      handler.postMessage({
        type: "action",
        name: "saveImageToDownloads",
        requestId,
        filename,
        dataUrl,
      });
    } catch (error: any) {
      PENDING.delete(requestId);
      window.clearTimeout(timeoutId);
      resolve({ ok: false, error: error?.message || String(error) });
    }
  });
}
