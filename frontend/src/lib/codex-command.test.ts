import { beforeEach, describe, expect, it, vi } from 'vitest';

const harness = vi.hoisted(() => ({
  nextId: 0,
  resetCount: 0,
  logs: [] as Array<Record<string, unknown>>,
  state: null as any,
  streamCodexTurn: vi.fn(),
  fetchHistory: vi.fn(),
  refreshCodexDesktop: vi.fn(),
}));

vi.mock('./api', () => ({
  fetchCodexThreadHistory: (...args: unknown[]) => harness.fetchHistory(...args),
  requestCodexDesktopRefresh: (...args: unknown[]) => harness.refreshCodexDesktop(...args),
}));

vi.mock('./store', () => ({
  generateId: () => `generated-${++harness.nextId}`,
  useAppStore: {
    getState: () => harness.state,
  },
}));

vi.mock('./sse', () => ({
  streamCodexTurn: (...args: unknown[]) => harness.streamCodexTurn(...args),
}));

import {
  isCodexConversationDispatchActive,
  sendCodexConversationMessage,
} from './codex-command';

function createState(staleStreaming = false) {
  const conversation = {
    id: 'conversation-a',
    title: 'Existing Codex thread',
    createdAt: 1,
    updatedAt: 1,
    model: 'codex',
    messages: [] as any[],
    codexThreadId: 'thread-a',
    codexProjectCwd: 'D:\\dev\\workspaces\\openjarvis',
  };
  const state: any = {
    activeId: conversation.id,
    conversations: [conversation],
    messages: conversation.messages,
    selectedModel: 'codex',
    settings: { temperature: 0.2, maxTokens: 4096, refreshCodexDesktop: true },
    streamState: {
      isStreaming: staleStreaming,
      owner: null,
      phase: staleStreaming ? 'stale' : '',
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    },
    addMessage: (_conversationId: string, message: any) => {
      conversation.messages.push(message);
      state.messages = conversation.messages;
    },
    updateLastAssistant: (_conversationId: string, content: string) => {
      const last = conversation.messages[conversation.messages.length - 1];
      if (last?.role === 'assistant') last.content = content;
    },
    setStreamState: (partial: Record<string, unknown>) => {
      state.streamState = { ...state.streamState, ...partial };
    },
    resetStream: () => {
      harness.resetCount += 1;
      state.streamState = {
        isStreaming: false,
        owner: null,
        phase: '',
        elapsedMs: 0,
        activeToolCalls: [],
        content: '',
      };
    },
    addLogEntry: (entry: Record<string, unknown>) => {
      harness.logs.push(entry);
    },
  };
  return state;
}

beforeEach(() => {
  harness.nextId = 0;
  harness.resetCount = 0;
  harness.logs = [];
  harness.state = createState();
  harness.streamCodexTurn.mockReset();
  harness.fetchHistory.mockReset();
  harness.refreshCodexDesktop.mockReset();
  harness.refreshCodexDesktop.mockResolvedValue({
    status: 'accepted',
    thread_id: 'thread-a',
    uri: 'codex://threads/thread-a',
  });
  harness.fetchHistory.mockResolvedValue({ thread_id: 'thread-a', messages: [] });
});

describe('shared Codex conversation dispatcher', () => {
  it('sends the pure message to the selected existing thread and releases stale UI state', async () => {
    harness.state = createState(true);
    harness.streamCodexTurn.mockImplementation(async function* () {
      yield {
        data: JSON.stringify({
          choices: [{ delta: { content: 'Resposta real' }, finish_reason: 'stop' }],
        }),
      };
    });

    const result = await sendCodexConversationMessage('  mensagem pura  ', {
      origin: 'jarvis',
    });

    expect(result).toBe('Resposta real');
    expect(harness.resetCount).toBe(2);
    expect(harness.streamCodexTurn).toHaveBeenCalledTimes(1);
    expect(harness.refreshCodexDesktop).toHaveBeenCalledTimes(2);
    expect(harness.refreshCodexDesktop).toHaveBeenNthCalledWith(1, 'thread-a');
    expect(harness.refreshCodexDesktop).toHaveBeenNthCalledWith(2, 'thread-a');
    const [threadId, request] = harness.streamCodexTurn.mock.calls[0];
    expect(threadId).toBe('thread-a');
    expect(request).toMatchObject({
      message: 'mensagem pura',
      conversation_id: 'conversation-a',
      project_cwd: 'D:\\dev\\workspaces\\openjarvis',
      client_user_message_id: 'generated-1',
    });
    expect(harness.state.conversations[0].messages.map((message: any) => message.content)).toEqual([
      'mensagem pura',
      'Resposta real',
    ]);
    expect(harness.state.streamState.isStreaming).toBe(false);
    expect(isCodexConversationDispatchActive('conversation-a')).toBe(false);
    expect(JSON.stringify(harness.logs)).not.toContain('mensagem pura');
    expect(harness.logs[0]?.message).toContain('request_id=generated-1');
    expect(harness.logs[0]?.message).toContain('text_length=13');
  });

  it('keeps the completed response when the optional Desktop refresh fails', async () => {
    harness.streamCodexTurn.mockImplementation(async function* () {
      yield {
        data: JSON.stringify({
          choices: [{ delta: { content: 'persistida' }, finish_reason: 'stop' }],
        }),
      };
    });
    harness.refreshCodexDesktop.mockRejectedValue(new Error('Desktop indisponível'));

    await expect(sendCodexConversationMessage('mensagem')).resolves.toBe('persistida');
    expect(harness.state.conversations[0].messages.at(-1)?.content).toBe('persistida');
    expect(harness.refreshCodexDesktop).toHaveBeenCalledTimes(2);
  });

  it('treats a structured SSE agent error as a failed dispatch', async () => {
    harness.streamCodexTurn.mockImplementation(async function* () {
      yield { event: 'error', data: JSON.stringify({ detail: 'CODEX_BUSY' }) };
    });

    await expect(sendCodexConversationMessage('mensagem')).rejects.toThrow('CODEX_BUSY');
    expect(harness.refreshCodexDesktop).toHaveBeenCalledTimes(1);
    expect(harness.state.conversations[0].messages.at(-1)?.content).toContain(
      'Falha de envio: CODEX_BUSY',
    );
  });

  it('rejects the legacy error-as-assistant-text envelope', async () => {
    harness.streamCodexTurn.mockImplementation(async function* () {
      yield {
        data: JSON.stringify({
          choices: [
            {
              delta: { content: 'Error during generation: CODEX_THREAD_STATUS_TIMEOUT' },
              finish_reason: 'stop',
            },
          ],
        }),
      };
    });

    await expect(sendCodexConversationMessage('mensagem')).rejects.toThrow(
      'CODEX_THREAD_STATUS_TIMEOUT',
    );
    expect(harness.refreshCodexDesktop).toHaveBeenCalledTimes(1);
  });

  it('recovers the canonical Codex answer when the stream has no content delta', async () => {
    harness.streamCodexTurn.mockImplementation(async function* () {
      yield {
        data: JSON.stringify({
          choices: [{ delta: {}, finish_reason: 'stop' }],
        }),
      };
    });
    harness.fetchHistory.mockResolvedValue({
      thread_id: 'thread-a',
      messages: [
        { message_id: 'user-1', role: 'user', content: 'mensagem' },
        { message_id: 'assistant-1', role: 'assistant', content: 'Relatório completo persistido.' },
      ],
    });

    await expect(sendCodexConversationMessage('mensagem')).resolves.toBe(
      'Relatório completo persistido.',
    );
    expect(harness.fetchHistory).toHaveBeenCalledWith('thread-a');
    expect(harness.state.conversations[0].messages.at(-1)?.content).toBe(
      'Relatório completo persistido.',
    );
  });

  it('replaces a transport acknowledgement with the canonical answer', async () => {
    harness.streamCodexTurn.mockImplementation(async function* () {
      yield {
        data: JSON.stringify({
          choices: [{ delta: { content: 'Comando concluído pelo Codex.' }, finish_reason: 'stop' }],
        }),
      };
    });
    harness.fetchHistory
      .mockResolvedValueOnce({ thread_id: 'thread-a', messages: [] })
      .mockResolvedValueOnce({
        thread_id: 'thread-a',
        messages: [
          { message_id: 'user-1', role: 'user', content: 'mensagem' },
          { message_id: 'assistant-1', role: 'assistant', content: 'Resposta detalhada persistida.' },
        ],
      });

    await expect(sendCodexConversationMessage('mensagem')).resolves.toBe(
      'Resposta detalhada persistida.',
    );
    expect(harness.fetchHistory).toHaveBeenCalledTimes(2);
  });

  it('does not remount Codex Desktop when the user disables the setting', async () => {
    harness.state.settings.refreshCodexDesktop = false;
    harness.streamCodexTurn.mockImplementation(async function* () {
      yield {
        data: JSON.stringify({
          choices: [{ delta: { content: 'feito' }, finish_reason: 'stop' }],
        }),
      };
    });

    await expect(sendCodexConversationMessage('mensagem')).resolves.toBe('feito');
    expect(harness.refreshCodexDesktop).not.toHaveBeenCalled();
  });

  it('blocks only a genuinely active shared dispatch and unlocks after completion', async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    harness.streamCodexTurn.mockImplementation(async function* () {
      await gate;
      yield {
        data: JSON.stringify({
          choices: [{ delta: { content: 'feito' }, finish_reason: 'stop' }],
        }),
      };
    });

    const first = sendCodexConversationMessage('primeira');
    await vi.waitFor(() => expect(isCodexConversationDispatchActive('conversation-a')).toBe(true));
    await expect(sendCodexConversationMessage('segunda')).rejects.toThrow(
      'já está executando outra solicitação enviada pelo OpenJarvis',
    );

    release();
    await expect(first).resolves.toBe('feito');
    expect(isCodexConversationDispatchActive('conversation-a')).toBe(false);
  });
});
