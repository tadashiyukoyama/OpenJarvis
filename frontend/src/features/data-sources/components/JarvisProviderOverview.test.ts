import { describe, expect, it } from 'vitest';
import type { JarvisAgentProvider } from '@/features/jarvis/api/types';
import { providerStatus } from './JarvisProviderOverview';

function provider(
  id: string,
  status: string,
  connected = false,
  operational = connected,
): JarvisAgentProvider {
  return { id, status, connected, operational, capabilities: [], reason: null };
}

describe('canonical provider presentation', () => {
  it('shows operational but unprobed e-mail honestly', () => {
    expect(providerStatus(
      provider('acelerachat_email', 'configured_not_probed', false, true),
    )).toBe(
      'operacional · conexão não sondada',
    );
  });

  it('shows a provider as connected only from the canonical state', () => {
    expect(providerStatus(provider('acelerachat_whatsapp', 'connected', true))).toBe(
      'conectado',
    );
  });
});
