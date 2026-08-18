import { apiFetch } from './api';
import type { GeminiLiveClientDiagnostics } from './gemini-live';

export interface JarvisLiveStatus {
  configured: boolean;
  primary_configured: boolean;
  fallback_configured: boolean;
  primary_available: boolean;
  fallback_available: boolean;
  model: string;
  websocket_endpoint: string;
  failover_policy: 'auth_or_transient_only';
  quota_policy: 'preserve_and_wait';
}

export interface JarvisLiveToken {
  token: string;
  credential_slot: 'primary' | 'fallback';
  fallback_active: boolean;
  model: string;
  expires_at: string;
  websocket_endpoint: string;
}

export type JarvisOperationalEventType =
  | 'system'
  | 'user'
  | 'jarvis'
  | 'codex'
  | 'approval'
  | 'error'
  | 'tool'
  | 'dispatch'
  | 'session';

export interface JarvisOperationalEvent {
  event_id: string;
  thread_id: string;
  project_cwd: string;
  event_type: JarvisOperationalEventType;
  text: string;
  occurred_at: number;
}

export class JarvisLiveApiError extends Error {
  kind: string;
  commandPreserved: boolean;
  retryAfterSeconds: number | null;

  constructor(
    message: string,
    options: {
      kind?: string;
      commandPreserved?: boolean;
      retryAfterSeconds?: number | null;
    } = {},
  ) {
    super(message);
    this.name = 'JarvisLiveApiError';
    this.kind = options.kind ?? 'unknown';
    this.commandPreserved = options.commandPreserved ?? false;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

export async function fetchJarvisLiveStatus(): Promise<JarvisLiveStatus> {
  const response = await apiFetch('/v1/jarvis/live/status');
  if (!response.ok) {
    throw new JarvisLiveApiError(`Status do Gemini Live indisponível: ${response.status}`);
  }
  return response.json();
}

export async function createJarvisLiveToken(): Promise<JarvisLiveToken> {
  const response = await apiFetch('/v1/jarvis/live/token', { method: 'POST' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body?.detail ?? {};
    throw new JarvisLiveApiError(
      typeof detail.message === 'string'
        ? detail.message
        : `Não foi possível iniciar o Gemini Live: ${response.status}`,
      {
        kind: typeof detail.kind === 'string' ? detail.kind : 'unknown',
        commandPreserved: detail.command_preserved === true,
        retryAfterSeconds:
          typeof detail.retry_after_seconds === 'number'
            ? detail.retry_after_seconds
            : null,
      },
    );
  }
  return response.json();
}

export async function appendGeminiLiveClientDiagnostics(
  diagnostics: GeminiLiveClientDiagnostics,
): Promise<void> {
  const response = await apiFetch('/v1/jarvis/live/diagnostics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(diagnostics),
  });
  if (!response.ok) {
    throw new JarvisLiveApiError(
      `Telemetria de áudio indisponível: ${response.status}`,
    );
  }
}

export async function fetchJarvisOperationalEvents(
  threadId: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<JarvisOperationalEvent[]> {
  const params = new URLSearchParams({
    thread_id: threadId,
    limit: String(Math.min(100, Math.max(1, limit))),
  });
  const response = await apiFetch(`/v1/jarvis/live/events?${params}`, { signal });
  if (!response.ok) {
    throw new JarvisLiveApiError(
      `Memória operacional do Jarvis indisponível: ${response.status}`,
    );
  }
  const body = await response.json();
  return Array.isArray(body?.events) ? body.events : [];
}

export async function appendJarvisOperationalEvent(
  event: JarvisOperationalEvent,
): Promise<JarvisOperationalEvent> {
  const response = await apiFetch('/v1/jarvis/live/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
  });
  if (!response.ok) {
    throw new JarvisLiveApiError(
      `Não foi possível registrar a memória operacional: ${response.status}`,
    );
  }
  return response.json();
}
