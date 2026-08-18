import { describe, expect, it } from 'vitest';
import {
  prependCodexHistoryPage,
  usesFiniteCodexSync,
} from './codex-sync-transport';

describe('Codex synchronization transport selection', () => {
  it('uses finite polling for Cloudflare Quick Tunnels', () => {
    expect(usesFiniteCodexSync('example.trycloudflare.com')).toBe(true);
    expect(usesFiniteCodexSync('EXAMPLE.TRYCLOUDFLARE.COM')).toBe(true);
  });

  it('keeps SSE for local and named tunnel hosts', () => {
    expect(usesFiniteCodexSync('127.0.0.1')).toBe(false);
    expect(usesFiniteCodexSync('jarvis.example.com')).toBe(false);
  });

  it('prepends finite history pages chronologically and removes overlap', () => {
    const current = {
      thread_id: 'thread-a',
      messages: [
        { message_id: 'm2', role: 'assistant' as const, content: 'two', timestamp: 2 },
        { message_id: 'm3', role: 'user' as const, content: 'three', timestamp: 3 },
      ],
      complete: false,
      next_cursor: 'older',
    };
    const older = {
      thread_id: 'thread-a',
      messages: [
        { message_id: 'm1', role: 'user' as const, content: 'one', timestamp: 1 },
        { message_id: 'm2', role: 'assistant' as const, content: 'two', timestamp: 2 },
      ],
      complete: true,
      next_cursor: null,
    };

    const combined = prependCodexHistoryPage(current, older);

    expect(combined.messages.map((message) => message.message_id)).toEqual(['m1', 'm2', 'm3']);
    expect(combined.complete).toBe(true);
    expect(combined.next_cursor).toBeNull();
  });
});
