import { apiFetch } from './api';

export type EvolutionWhatsAppStatus = {
  provider: 'evolution_api' | string;
  configured: boolean;
  instance_name: string;
  instance_exists: boolean;
  state: string;
  connected: boolean;
  qr_available: boolean;
  error_code?: string;
  external_effects?: string;
  provisioning_enabled?: boolean;
};

export type EvolutionWhatsAppQr = EvolutionWhatsAppStatus & {
  available: boolean;
  qr: string | null;
  base64: string | null;
};

async function getJson<T>(
  path: string,
  signal?: AbortSignal,
  init: RequestInit = {},
): Promise<T> {
  const response = await apiFetch(path, { ...init, signal, cache: 'no-store' });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Evolution API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchEvolutionStatus(signal?: AbortSignal) {
  return getJson<EvolutionWhatsAppStatus>('/v1/integrations/whatsapp/evolution/status', signal);
}

export function fetchEvolutionQr(signal?: AbortSignal) {
  return getJson<EvolutionWhatsAppQr>('/v1/integrations/whatsapp/evolution/qr', signal);
}

export function provisionEvolution(signal?: AbortSignal) {
  return getJson<EvolutionWhatsAppStatus & { provisioned: boolean }>(
    '/v1/integrations/whatsapp/evolution/provision',
    signal,
    { method: 'POST' },
  );
}
