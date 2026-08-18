import { afterEach, describe, expect, it, vi } from 'vitest';

import { checkHealth } from './api';

describe('checkHealth', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('probes the configured backend before the relative Vite proxy', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(checkHealth()).resolves.toBe(true);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/health$/);
  });
});
