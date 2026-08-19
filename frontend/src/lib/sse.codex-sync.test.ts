import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamCodexThreadUpdates } from './sse';

const encoder = new TextEncoder();

function streamingResponse(chunks: string[]): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

describe('streamCodexThreadUpdates', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('parses a snapshot split across transport chunks', async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamingResponse([
      'id: revision-1\nevent: snap',
      'shot\ndata: {"thread_id":"thread-a","messages":[',
      '{"message_id":"m1","role":"user","content":"ola","timestamp":1}]}\n\n',
    ]));
    vi.stubGlobal('fetch', fetchMock);

    const stream = streamCodexThreadUpdates('thread-a');
    const first = await stream.next();
    await stream.return(undefined);

    expect(first.done).toBe(false);
    expect(first.value).toEqual({
      type: 'snapshot',
      history: {
        thread_id: 'thread-a',
        messages: [
          {
            message_id: 'm1',
            role: 'user',
            content: 'ola',
            timestamp: 1,
          },
        ],
      },
    });
    expect(String(fetchMock.mock.calls[0][0])).toMatch(
      /\/v1\/codex\/threads\/thread-a\/events$/,
    );
    expect(fetchMock.mock.calls[0][1]).toEqual(
      expect.objectContaining({ headers: {} }),
    );
  });

  it('rejects a snapshot for a different thread', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([
      'event: snapshot\ndata: {"thread_id":"thread-b","messages":[]}\n\n',
    ])));

    const stream = streamCodexThreadUpdates('thread-a');

    await expect(stream.next()).rejects.toThrow(
      'Codex synchronization returned the wrong thread',
    );
  });

  it('surfaces a sanitized backend error event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([
      'event: error\ndata: {"detail":"temporarily unavailable"}\n\n',
    ])));

    const stream = streamCodexThreadUpdates('thread-a');

    await expect(stream.next()).rejects.toThrow('temporarily unavailable');
  });

  it('parses a live assistant delta', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([
      'event: delta\ndata: {"thread_id":"thread-a","turn_id":"turn-1","delta":"olá"}\n\n',
    ])));

    const stream = streamCodexThreadUpdates('thread-a');
    const first = await stream.next();
    await stream.return(undefined);

    expect(first.value).toEqual({
      type: 'delta',
      delta: {
        thread_id: 'thread-a',
        turn_id: 'turn-1',
        delta: 'olá',
      },
    });
  });

  it('parses a canonical public message event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([
      'event: message\ndata: {"thread_id":"thread-a","turn_id":"turn-1",',
      '"message":{"message_id":"user-1","role":"user",',
      '"content":"novo","timestamp":1}}\n\n',
    ])));

    const stream = streamCodexThreadUpdates('thread-a');
    const first = await stream.next();
    await stream.return(undefined);

    expect(first.value).toEqual({
      type: 'message',
      message: {
        thread_id: 'thread-a',
        turn_id: 'turn-1',
        message: {
          message_id: 'user-1',
          role: 'user',
          content: 'novo',
          timestamp: 1,
        },
      },
    });
  });

  it('parses an ordered real execution event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([
      'event: execution\ndata: {"thread_id":"thread-a",',
      '"turn_id":"turn-1","item_id":"item-1",',
      '"event_type":"item_started","state":"running",',
      '"action_summary":"Executando testes.","sequence":12}\n\n',
    ])));

    const stream = streamCodexThreadUpdates('thread-a');
    const first = await stream.next();
    await stream.return(undefined);

    expect(first.value).toEqual({
      type: 'execution',
      execution: {
        thread_id: 'thread-a',
        turn_id: 'turn-1',
        item_id: 'item-1',
        event_type: 'item_started',
        state: 'running',
        action_summary: 'Executando testes.',
        sequence: 12,
      },
    });
  });

  it('keeps a degraded history state inside the live stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([
      'event: status\ndata: {"thread_id":"thread-a","state":"connected"}\n\n',
      'event: status\ndata: {"thread_id":"thread-a","state":"degraded",',
      '"detail":"Codex history is catching up","retry_in_seconds":2}\n\n',
    ])));

    const stream = streamCodexThreadUpdates('thread-a');
    const connected = await stream.next();
    const degraded = await stream.next();
    await stream.return(undefined);

    expect(connected.value).toEqual({
      type: 'status',
      status: { thread_id: 'thread-a', state: 'connected' },
    });
    expect(degraded.value).toEqual({
      type: 'status',
      status: {
        thread_id: 'thread-a',
        state: 'degraded',
        detail: 'Codex history is catching up',
        retry_in_seconds: 2,
      },
    });
  });
});
