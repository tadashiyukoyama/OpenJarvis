import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchEvolutionQr, fetchEvolutionStatus, provisionEvolution } from './evolution-api';

describe('Evolution WhatsApp integration API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses the authenticated backend status route with cache disabled', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        provider: 'evolution_api',
        configured: true,
        instance_name: 'jarvis',
        instance_exists: false,
        state: 'not_provisioned',
        connected: false,
        qr_available: false,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchEvolutionStatus();

    expect(result.state).toBe('not_provisioned');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/integrations/whatsapp/evolution/status'),
      expect.objectContaining({ cache: 'no-store' }),
    );
  });

  it('returns QR data only from the backend, never from a browser-held provider key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        provider: 'evolution_api',
        configured: true,
        instance_name: 'jarvis',
        instance_exists: true,
        state: 'connecting',
        connected: false,
        qr_available: true,
        available: true,
        qr: 'opaque-qr',
        base64: null,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchEvolutionQr();

    expect(result.qr).toBe('opaque-qr');
    expect(fetchMock.mock.calls[0][0]).toContain('/v1/integrations/whatsapp/evolution/qr');
    expect(JSON.stringify(fetchMock.mock.calls[0][1])).not.toContain('apikey');
  });

  it('uses the explicit provisioning route without sending provider credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ provisioned: false, error_code: 'EVOLUTION_PROVISIONING_DISABLED' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await provisionEvolution();

    expect(result.provisioned).toBe(false);
    expect(fetchMock.mock.calls[0][0]).toContain('/v1/integrations/whatsapp/evolution/provision');
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST', cache: 'no-store' });
    expect(JSON.stringify(fetchMock.mock.calls[0][1])).not.toContain('apikey');
  });
});
