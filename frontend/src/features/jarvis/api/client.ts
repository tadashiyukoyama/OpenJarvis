import { apiFetch } from '@/lib/api';
import type {
  JarvisAgentAction,
  JarvisAgentCatalog,
  JarvisAgentEvent,
  JarvisAgentJob,
  JarvisAgentSession,
  JarvisEdgeApproval,
  JsonObject,
} from './types';

interface ErrorBody {
  detail?: string | { code?: string; message?: string };
  code?: string;
  message?: string;
}
export class JarvisAgentApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'JarvisAgentApiError';
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    },
  });
  const body = (await response.json().catch(() => ({}))) as ErrorBody & T;
  if (!response.ok) {
    const detail = body.detail;
    const structured = typeof detail === 'object' && detail !== null ? detail : null;
    throw new JarvisAgentApiError(
      structured?.code ?? body.code ?? `HTTP_${response.status}`,
      structured?.message
        ?? body.message
        ?? (typeof detail === 'string' ? detail : `Jarvis Agent HTTP ${response.status}`),
      response.status,
    );
  }
  return body;
}

export function fetchJarvisAgentCatalog(signal?: AbortSignal): Promise<JarvisAgentCatalog> {
  return requestJson('/v1/jarvis/agent/catalog', { signal });
}

export async function fetchJarvisAgentThreadEvents(
  projectKey: string,
  codexThreadId: string,
  limit = 100,
  signal?: AbortSignal,
): Promise<JarvisAgentEvent[]> {
  const query = new URLSearchParams({
    project_key: projectKey,
    codex_thread_id: codexThreadId,
    limit: String(Math.min(500, Math.max(1, limit))),
  });
  const response = await requestJson<{ events: JarvisAgentEvent[] }>(
    `/v1/jarvis/agent/events/history?${query}`,
    { signal },
  );
  return response.events;
}

export function createJarvisAgentSession(
  projectKey: string,
  codexThreadId: string,
  signal?: AbortSignal,
): Promise<JarvisAgentSession> {
  return requestJson('/v1/jarvis/agent/sessions', {
    method: 'POST',
    signal,
    body: JSON.stringify({ project_key: projectKey, codex_thread_id: codexThreadId }),
  });
}

export function commitJarvisAgentTurn(
  session: JarvisAgentSession,
  turnId: string,
  transcript: string,
): Promise<JsonObject> {
  return requestJson(`/v1/jarvis/agent/sessions/${encodeURIComponent(session.session_id)}/turns`, {
    method: 'POST',
    body: JSON.stringify({
      generation: session.generation,
      turn_id: turnId,
      transcript,
      final: true,
    }),
  });
}

export async function proposeJarvisAgentAction(
  session: JarvisAgentSession,
  functionCallId: string,
  name: string,
  args: JsonObject,
  turnId?: string,
): Promise<JarvisAgentAction> {
  const response = await requestJson<{ result: JarvisAgentAction }>(
    `/v1/jarvis/agent/sessions/${encodeURIComponent(session.session_id)}/proposals`,
    {
      method: 'POST',
      body: JSON.stringify({
        generation: session.generation,
        function_call_id: functionCallId,
        name,
        arguments: args,
        turn_id: turnId ?? null,
      }),
    },
  );
  return response.result;
}

export async function decideJarvisAgentAction(
  action: JarvisAgentAction,
  decision: 'approve' | 'deny',
): Promise<JarvisAgentAction> {
  const response = await requestJson<{ result: JarvisAgentAction }>(
    `/v1/jarvis/agent/actions/${encodeURIComponent(action.action_id)}/decision`,
    {
      method: 'POST',
      headers: { 'X-Jarvis-Decision-Channel': 'visual' },
      body: JSON.stringify({
        session_id: action.session_id,
        payload_hash: action.payload_hash,
        decision,
      }),
    },
  );
  return response.result;
}

export async function fetchJarvisAgentAction(actionId: string): Promise<JarvisAgentAction> {
  const response = await requestJson<{ result: JarvisAgentAction }>(
    `/v1/jarvis/agent/actions/${encodeURIComponent(actionId)}`,
  );
  return response.result;
}

export async function fetchJarvisAgentJob(jobId: string): Promise<JarvisAgentJob> {
  const response = await requestJson<{ result: JarvisAgentJob }>(
    `/v1/jarvis/agent/jobs/${encodeURIComponent(jobId)}`,
  );
  return response.result;
}

export async function decideJarvisEdgeApproval(
  approval: JarvisEdgeApproval,
  decision: 'approve' | 'deny',
): Promise<JsonObject> {
  const response = await requestJson<{ result: JsonObject }>(
    `/v1/jarvis/agent/edge/approvals/${encodeURIComponent(approval.approval_id)}/decision`,
    {
      method: 'POST',
      headers: { 'X-Jarvis-Decision-Channel': 'visual' },
      body: JSON.stringify({ payload_hash: approval.payload_hash, decision }),
    },
  );
  return response.result;
}

export function closeJarvisAgentSession(session: JarvisAgentSession): Promise<JsonObject> {
  return requestJson(
    `/v1/jarvis/agent/sessions/${encodeURIComponent(session.session_id)}/close`,
    {
      method: 'POST',
      body: JSON.stringify({ generation: session.generation }),
    },
  );
}

function parseEventBlock(block: string): JarvisAgentEvent | null {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n');
  if (!data) return null;
  try {
    return JSON.parse(data) as JarvisAgentEvent;
  } catch {
    return null;
  }
}

function usesQuickTunnel(
  hostname = typeof window !== 'undefined' ? window.location.hostname : '',
): boolean {
  return hostname.toLowerCase().endsWith('.trycloudflare.com');
}

async function pollJarvisAgentEvents(
  after: number,
  onEvent: (event: JarvisAgentEvent) => void,
  signal: AbortSignal,
): Promise<number> {
  const response = await requestJson<{ events: JarvisAgentEvent[]; next_after: number }>(
    `/v1/jarvis/agent/events/poll?after=${Math.max(0, after)}&limit=100`,
    { signal },
  );
  for (const event of response.events) onEvent(event);
  return Math.max(after, response.next_after);
}

export async function streamJarvisAgentEvents(
  after: number,
  onEvent: (event: JarvisAgentEvent) => void,
  signal: AbortSignal,
): Promise<number> {
  // Cloudflare Quick Tunnels explicitly buffer text/event-stream.  A finite
  // event page preserves the same cursor/idempotency contract without
  // pretending that this transport can stream.
  if (usesQuickTunnel()) {
    return pollJarvisAgentEvents(after, onEvent, signal);
  }
  const response = await apiFetch(`/v1/jarvis/agent/events?after=${Math.max(0, after)}`, {
    signal,
    headers: { Accept: 'text/event-stream' },
  });
  if (!response.ok || !response.body) {
    throw new JarvisAgentApiError(
      `HTTP_${response.status}`,
      `Canal de eventos Jarvis indisponível (${response.status}).`,
      response.status,
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let cursor = after;
  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? '';
    for (const block of blocks) {
      const event = parseEventBlock(block);
      if (!event) continue;
      cursor = Math.max(cursor, event.sequence);
      onEvent(event);
    }
  }
  return cursor;
}

export const jarvisAgentClientInternals = { parseEventBlock, usesQuickTunnel };
