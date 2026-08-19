import type {
  CodexThreadHistory,
  CodexThreadExecutionEvent,
  CodexThreadMessageEvent,
  CodexThreadSyncEvent,
  CodexThreadSyncStatusEvent,
  ResearchEvent,
  SSEEvent,
} from '../types';
import { getBase, authHeaders } from './api';

export interface ChatRequest {
  model: string;
  messages: Array<{ role: string; content: string }>;
  stream: true;
  temperature?: number;
  max_tokens?: number;
  conversation_id?: string;
  conversation_scope?: string;
  codex_thread_id?: string;
  codex_project_cwd?: string;
  codex_client_user_message_id?: string;
}

export interface CodexTurnRequest {
  project_cwd: string;
  message: string;
  client_user_message_id: string;
  conversation_id: string;
}

function parseCodexSyncData(event: string, data: string): CodexThreadSyncEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    throw new Error('Codex synchronization returned invalid JSON');
  }
  if (event === 'error') {
    const detail = typeof parsed === 'object' && parsed !== null && 'detail' in parsed
      ? String(parsed.detail)
      : 'Codex synchronization failed';
    throw new Error(detail);
  }
  if (event === 'snapshot') {
    if (
      typeof parsed !== 'object'
      || parsed === null
      || !('thread_id' in parsed)
      || typeof parsed.thread_id !== 'string'
      || !('messages' in parsed)
      || !Array.isArray(parsed.messages)
    ) {
      throw new Error('Codex synchronization returned an invalid snapshot');
    }
    return { type: 'snapshot', history: parsed as CodexThreadHistory };
  }
  if (event === 'delta') {
    if (
      typeof parsed !== 'object'
      || parsed === null
      || !('thread_id' in parsed)
      || typeof parsed.thread_id !== 'string'
      || !('turn_id' in parsed)
      || typeof parsed.turn_id !== 'string'
      || !('delta' in parsed)
      || typeof parsed.delta !== 'string'
    ) {
      throw new Error('Codex synchronization returned an invalid delta');
    }
    return {
      type: 'delta',
      delta: {
        thread_id: parsed.thread_id,
        turn_id: parsed.turn_id,
        delta: parsed.delta,
      },
    };
  }
  if (event === 'message') {
    if (
      typeof parsed !== 'object'
      || parsed === null
      || !('thread_id' in parsed)
      || typeof parsed.thread_id !== 'string'
      || !('message' in parsed)
      || typeof parsed.message !== 'object'
      || parsed.message === null
      || !('message_id' in parsed.message)
      || typeof parsed.message.message_id !== 'string'
      || !('role' in parsed.message)
      || !['user', 'assistant'].includes(String(parsed.message.role))
      || !('content' in parsed.message)
      || typeof parsed.message.content !== 'string'
    ) {
      throw new Error('Codex synchronization returned an invalid message');
    }
    return {
      type: 'message',
      message: parsed as CodexThreadMessageEvent,
    };
  }
  if (event === 'execution') {
    const states = [
      'starting', 'running', 'working', 'completed', 'failed',
      'interrupted', 'cancelled', 'unknown',
    ];
    const eventTypes = [
      'turn_started', 'turn_completed', 'item_started', 'item_completed', 'status_changed',
    ];
    if (
      typeof parsed !== 'object'
      || parsed === null
      || !('thread_id' in parsed)
      || typeof parsed.thread_id !== 'string'
      || !('event_type' in parsed)
      || !eventTypes.includes(String(parsed.event_type))
      || !('state' in parsed)
      || !states.includes(String(parsed.state))
      || ('sequence' in parsed && (
        typeof parsed.sequence !== 'number'
        || !Number.isInteger(parsed.sequence)
        || parsed.sequence <= 0
      ))
    ) {
      throw new Error('Codex synchronization returned an invalid execution event');
    }
    return {
      type: 'execution',
      execution: parsed as CodexThreadExecutionEvent,
    };
  }
  if (event === 'status') {
    if (
      typeof parsed !== 'object'
      || parsed === null
      || !('thread_id' in parsed)
      || typeof parsed.thread_id !== 'string'
      || !('state' in parsed)
      || !['connecting', 'connected', 'live', 'synchronizing', 'synchronized', 'degraded']
        .includes(String(parsed.state))
    ) {
      throw new Error('Codex synchronization returned an invalid status');
    }
    return {
      type: 'status',
      status: parsed as CodexThreadSyncStatusEvent,
    };
  }
  return null;
}

export async function* streamCodexThreadUpdates(
  threadId: string,
  signal?: AbortSignal,
): AsyncGenerator<CodexThreadSyncEvent> {
  const response = await fetch(
    `${getBase()}/v1/codex/threads/${encodeURIComponent(threadId)}/events`,
    { headers: authHeaders(), signal },
  );
  if (!response.ok) {
    let detail = `Codex synchronization failed: ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Keep the status-based error when the response is not JSON.
    }
    throw new Error(detail);
  }
  if (!response.body) throw new Error('Codex synchronization has no response body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';
  let dataLines: string[] = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (line === '') {
          if (dataLines.length > 0) {
            const update = parseCodexSyncData(currentEvent, dataLines.join('\n'));
            if (update) {
              const updateThreadId = update.type === 'snapshot'
                ? update.history.thread_id
                : update.type === 'delta'
                  ? update.delta.thread_id
                  : update.type === 'message'
                    ? update.message.thread_id
                    : update.type === 'execution'
                      ? update.execution.thread_id
                      : update.status.thread_id;
              if (updateThreadId !== threadId) {
                throw new Error('Codex synchronization returned the wrong thread');
              }
              yield update;
            }
          }
          currentEvent = '';
          dataLines = [];
        } else if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
  if (!signal?.aborted) throw new Error('Codex synchronization stream ended');
}

export async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const base = getBase();
  const response = await fetch(`${base}/v1/chat/completions`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  yield* streamSseResponse(response);
}

export async function* streamCodexTurn(
  threadId: string,
  request: CodexTurnRequest,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const response = await fetch(
    `${getBase()}/v1/codex/threads/${encodeURIComponent(threadId)}/turns`,
    {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(request),
      signal,
    },
  );
  if (!response.ok) {
    let detail = `Codex request failed: ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Keep the status-based error when the response is not JSON.
    }
    throw new Error(detail);
  }
  yield* streamSseResponse(response);
}

async function* streamSseResponse(
  response: Response,
): AsyncGenerator<SSEEvent> {
  if (!response.body) throw new Error('Streaming response has no body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent: string | undefined;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') return;
          yield { event: currentEvent, data };
          currentEvent = undefined;
        } else if (line.trim() === '') {
          currentEvent = undefined;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function* streamResearch(
  query: string,
  model?: string,
  signal?: AbortSignal,
): AsyncGenerator<ResearchEvent> {
  // /api/research is mounted at the server root — strip any trailing /v1
  // from the base so configurations like "http://host:8000/v1" still resolve.
  const base = getBase().replace(/\/v1\/?$/, '');
  const response = await fetch(`${base}/api/research`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ query, ...(model ? { model } : {}) }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Research request failed: ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') return;
        try {
          const parsed = JSON.parse(data) as ResearchEvent;
          yield parsed;
          if (parsed.type === 'done') return;
        } catch {
          // skip malformed chunks
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
