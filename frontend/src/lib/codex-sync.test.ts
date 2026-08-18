import { describe, expect, it } from 'vitest';
import type { ChatMessage, CodexThreadHistory } from '../types';
import {
  applyCodexLiveDelta,
  applyCodexLiveMessage,
  codexMessageSequenceEquals,
  reconcileCodexHistoryMessages,
} from './codex-sync';

const history: CodexThreadHistory = {
  thread_id: 'thread-a',
  messages: [
    { message_id: 'user-1', role: 'user', content: 'ola', timestamp: 10 },
    { message_id: 'assistant-1', role: 'assistant', content: 'oi', timestamp: null },
  ],
};

describe('reconcileCodexHistoryMessages', () => {
  it('creates stable canonical messages', () => {
    const first = reconcileCodexHistoryMessages(history, [], 20_000);
    const second = reconcileCodexHistoryMessages(history, first, 90_000);

    expect(first).toEqual([
      {
        id: 'codex-thread-a-user-1',
        role: 'user',
        content: 'ola',
        timestamp: 10_000,
      },
      {
        id: 'codex-thread-a-assistant-1',
        role: 'assistant',
        content: 'oi',
        timestamp: 20_001,
      },
    ]);
    expect(codexMessageSequenceEquals(first, second)).toBe(true);
  });

  it('preserves local telemetry when public content matches', () => {
    const local: ChatMessage[] = [
      { id: 'local-user', role: 'user', content: 'ola', timestamp: 1 },
      {
        id: 'local-assistant',
        role: 'assistant',
        content: 'oi',
        timestamp: 2,
        usage: { prompt_tokens: 3, completion_tokens: 4, total_tokens: 7 },
      },
    ];

    const reconciled = reconcileCodexHistoryMessages(history, local, 20_000);

    expect(reconciled[1].id).toBe('codex-thread-a-assistant-1');
    expect(reconciled[1].usage).toEqual({
      prompt_tokens: 3,
      completion_tokens: 4,
      total_tokens: 7,
    });
  });

  it('does not remove a local tail for a stale prefix snapshot', () => {
    const local: ChatMessage[] = [
      { id: 'local-user', role: 'user', content: 'ola', timestamp: 1 },
      { id: 'local-assistant', role: 'assistant', content: 'oi', timestamp: 2 },
    ];
    const stale: CodexThreadHistory = {
      thread_id: 'thread-a',
      messages: [history.messages[0]],
    };

    expect(reconcileCodexHistoryMessages(stale, local, 20_000)).toBe(local);
  });

  it('replaces only the authoritative tail for a partial latest window', () => {
    const local: ChatMessage[] = [
      { id: 'codex-thread-a-old', role: 'user', content: 'antiga', timestamp: 1 },
      { id: 'codex-thread-a-user-1', role: 'user', content: 'ola', timestamp: 2 },
      { id: 'stale', role: 'assistant', content: 'estado antigo', timestamp: 3 },
    ];
    const partial: CodexThreadHistory = { ...history, complete: false };

    const reconciled = reconcileCodexHistoryMessages(partial, local, 20_000);

    expect(reconciled.map((message) => message.content)).toEqual([
      'antiga',
      'ola',
      'oi',
    ]);
  });

  it('aligns repeated messages with the most recent matching sequence', () => {
    const local: ChatMessage[] = [
      { id: 'old-sim', role: 'user', content: 'Sim.', timestamp: 1 },
      { id: 'old-ok', role: 'assistant', content: 'OK', timestamp: 2 },
      { id: 'context', role: 'assistant', content: 'outro assunto', timestamp: 3 },
      { id: 'new-sim', role: 'user', content: 'Sim.', timestamp: 4 },
      {
        id: 'new-ok',
        role: 'assistant',
        content: 'OK',
        timestamp: 5,
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      },
    ];
    const repeated: CodexThreadHistory = {
      thread_id: 'thread-a',
      complete: false,
      messages: [
        { message_id: 'user-new', role: 'user', content: 'Sim.', timestamp: 4 },
        { message_id: 'assistant-new', role: 'assistant', content: 'OK', timestamp: 5 },
      ],
    };

    const reconciled = reconcileCodexHistoryMessages(repeated, local, 20_000);

    expect(reconciled.map((message) => message.id)).toEqual([
      'old-sim',
      'old-ok',
      'context',
      'codex-thread-a-user-new',
      'codex-thread-a-assistant-new',
    ]);
    expect(reconciled[4].usage).toEqual({
      prompt_tokens: 1,
      completion_tokens: 1,
      total_tokens: 2,
    });
  });
});

describe('applyCodexLiveDelta', () => {
  it('creates one stable assistant message and appends subsequent tokens', () => {
    const first = applyCodexLiveDelta([], 'thread-a', 'turn-live', 'ol', 100);
    const second = applyCodexLiveDelta(first, 'thread-a', 'turn-live', 'á', 200);

    expect(second).toEqual([
      {
        id: 'codex-thread-a-live-turn-live',
        role: 'assistant',
        content: 'olá',
        timestamp: 100,
      },
    ]);
  });

  it('ignores an empty delta without cloning messages', () => {
    const messages: ChatMessage[] = [];
    expect(applyCodexLiveDelta(messages, 'thread-a', 'turn-live', '', 100)).toBe(messages);
  });
});

describe('applyCodexLiveMessage', () => {
  it('replaces a streamed placeholder with the canonical final item', () => {
    const streaming = applyCodexLiveDelta([], 'thread-a', 'turn-live', 'resposta', 100);

    const completed = applyCodexLiveMessage(
      streaming,
      {
        thread_id: 'thread-a',
        turn_id: 'turn-live',
        message: {
          message_id: 'assistant-final',
          role: 'assistant',
          content: 'resposta',
          timestamp: null,
        },
      },
      200,
    );

    expect(completed).toEqual([
      {
        id: 'codex-thread-a-assistant-final',
        role: 'assistant',
        content: 'resposta',
        timestamp: 100,
      },
    ]);
  });
});
