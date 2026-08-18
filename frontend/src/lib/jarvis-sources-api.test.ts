import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  fetchWhatsAppQr,
  fetchWhatsAppStatus,
  reactWhatsAppMessage,
} from './jarvis-sources-api';

describe('WhatsApp Sources cache contract', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ['status', fetchWhatsAppStatus],
    ['qr', () => fetchWhatsAppQr()],
  ])('requests %s snapshots with the browser cache disabled', async (_, request) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      source: 'whatsapp_baileys',
      status: 'qr_required',
      qr_available: true,
      qr: 'private-test-qr',
      available: true,
      qr_generation: 1,
      qr_issued_at: '2026-08-08T13:40:01Z',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await request();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ cache: 'no-store' });
  });

  it('sends only an opaque message reference through the reaction endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'completed' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await reactWhatsAppMessage(
      { message_ref: 'wam_0123456789abcdefghijklmn', reaction: '👍' },
      'approval-token',
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({ 'X-Jarvis-Approval': 'approval-token' });
    expect(JSON.parse(init.body)).toEqual({
      message_ref: 'wam_0123456789abcdefghijklmn',
      reaction: '👍',
    });
  });
});
