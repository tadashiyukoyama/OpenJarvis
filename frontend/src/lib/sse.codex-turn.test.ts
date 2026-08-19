import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamCodexTurn } from './sse';

const encoder = new TextEncoder();

function streamingResponse(chunks: string[]): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { status: 200 });
}

describe('streamCodexTurn', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('posts one pure command to the selected thread endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamingResponse([
      'event: agent_turn_start\ndata: {"thread_id":"thread-a"}\n\n',
      'data: [DONE]\n\n',
    ]));
    vi.stubGlobal('fetch', fetchMock);
    const payload = {
      project_cwd: 'D:\\dev\\workspaces\\openjarvis',
      message: 'Faça a auditoria.',
      client_user_message_id: 'message-1',
      conversation_id: 'conversation-1',
    };

    const stream = streamCodexTurn('thread-a', payload);
    const first = await stream.next();
    await stream.return(undefined);

    expect(first.value).toEqual({
      event: 'agent_turn_start',
      data: '{"thread_id":"thread-a"}',
    });
    expect(String(fetchMock.mock.calls[0][0])).toMatch(
      /\/v1\/codex\/threads\/thread-a\/turns$/,
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(payload);
  });

  it('preserves the event name when data arrives in a later chunk', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([
      'event: error\n',
      'data: {"detail":"DEVICE_OFFLINE"}\n\n',
    ])));

    const stream = streamCodexTurn('thread-a', {
      project_cwd: 'D:\\dev\\workspaces\\openjarvis',
      message: 'Faça a auditoria.',
      client_user_message_id: 'message-1',
      conversation_id: 'conversation-1',
    });

    expect((await stream.next()).value).toEqual({
      event: 'error',
      data: '{"detail":"DEVICE_OFFLINE"}',
    });
  });
});
