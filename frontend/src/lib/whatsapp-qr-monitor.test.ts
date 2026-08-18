import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WhatsAppBaileysQrResponse } from './jarvis-sources-api';
import {
  shouldMonitorWhatsAppQr,
  WhatsAppQrMonitor,
} from './whatsapp-qr-monitor';

function snapshot(
  status: WhatsAppBaileysQrResponse['status'],
  generation: number,
): WhatsAppBaileysQrResponse {
  const available = status === 'qr_required';
  return {
    source: 'whatsapp_baileys',
    status,
    qr_available: available,
    qr: available ? `private-test-qr-${generation}` : '',
    available,
    qr_generation: generation,
    qr_issued_at: available ? `2026-08-08T13:40:0${generation}Z` : null,
  };
}

describe('WhatsAppQrMonitor', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps monitoring when the page opens with an existing QR and publishes rotations', async () => {
    const fetchSnapshot = vi.fn()
      .mockResolvedValueOnce(snapshot('qr_required', 1))
      .mockResolvedValueOnce(snapshot('qr_required', 2))
      .mockResolvedValueOnce(snapshot('connected', 2));
    const received: number[] = [];
    const monitor = new WhatsAppQrMonitor({
      fetchSnapshot,
      onSnapshot: (current) => received.push(current.qr_generation),
      onError: vi.fn(),
      intervalMs: 1_000,
    });

    monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(5_000);

    expect(received).toEqual([1, 2, 2]);
    expect(fetchSnapshot).toHaveBeenCalledTimes(3);
  });

  it('aborts an in-flight request when the component generation stops', async () => {
    let requestSignal: AbortSignal | undefined;
    const fetchSnapshot = vi.fn((signal: AbortSignal) => {
      requestSignal = signal;
      return new Promise<WhatsAppBaileysQrResponse>(() => undefined);
    });
    const monitor = new WhatsAppQrMonitor({
      fetchSnapshot,
      onSnapshot: vi.fn(),
      onError: vi.fn(),
    });

    monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    monitor.stop();

    expect(requestSignal?.aborted).toBe(true);
  });

  it('does not keep polling a terminal or disconnected state', async () => {
    const fetchSnapshot = vi.fn().mockResolvedValue(snapshot('disconnected', 0));
    const monitor = new WhatsAppQrMonitor({
      fetchSnapshot,
      onSnapshot: vi.fn(),
      onError: vi.fn(),
      intervalMs: 1_000,
    });

    monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(5_000);

    expect(fetchSnapshot).toHaveBeenCalledTimes(1);
    expect(shouldMonitorWhatsAppQr('auth_inconsistent')).toBe(false);
  });
});
