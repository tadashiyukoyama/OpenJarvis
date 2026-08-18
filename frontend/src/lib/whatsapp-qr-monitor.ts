import type {
  WhatsAppBaileysQrResponse,
  WhatsAppBaileysStatus,
} from './jarvis-sources-api';

const DEFAULT_INTERVAL_MS = 1_000;

export function shouldMonitorWhatsAppQr(status: WhatsAppBaileysStatus): boolean {
  return status === 'connecting' || status === 'qr_required';
}

interface WhatsAppQrMonitorOptions {
  fetchSnapshot: (signal: AbortSignal) => Promise<WhatsAppBaileysQrResponse>;
  onSnapshot: (snapshot: WhatsAppBaileysQrResponse) => void;
  onError: (error: unknown) => void;
  intervalMs?: number;
}

/**
 * Poll one atomic QR/status endpoint while a pairing is in progress.
 *
 * The monitor owns its timer and AbortController so unmounting the Sources
 * page cannot publish a late QR into a new component generation.
 */
export class WhatsAppQrMonitor {
  private readonly fetchSnapshot: WhatsAppQrMonitorOptions['fetchSnapshot'];
  private readonly onSnapshot: WhatsAppQrMonitorOptions['onSnapshot'];
  private readonly onError: WhatsAppQrMonitorOptions['onError'];
  private readonly intervalMs: number;
  private running = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private controller: AbortController | null = null;

  constructor(options: WhatsAppQrMonitorOptions) {
    this.fetchSnapshot = options.fetchSnapshot;
    this.onSnapshot = options.onSnapshot;
    this.onError = options.onError;
    this.intervalMs = options.intervalMs ?? DEFAULT_INTERVAL_MS;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    void this.tick();
  }

  stop(): void {
    this.running = false;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.controller?.abort();
    this.controller = null;
  }

  private schedule(): void {
    if (!this.running) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.tick();
    }, this.intervalMs);
  }

  private async tick(): Promise<void> {
    if (!this.running) return;
    const controller = new AbortController();
    this.controller = controller;
    try {
      const snapshot = await this.fetchSnapshot(controller.signal);
      if (!this.running || controller.signal.aborted) return;
      this.onSnapshot(snapshot);
      if (shouldMonitorWhatsAppQr(snapshot.status)) {
        this.schedule();
      } else {
        this.running = false;
      }
    } catch (error) {
      if (!this.running || controller.signal.aborted) return;
      this.running = false;
      this.onError(error);
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }
}
