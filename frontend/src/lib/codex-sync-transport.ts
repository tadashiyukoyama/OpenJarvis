import type { CodexThreadHistory } from '../types';

export const MAX_FINITE_HISTORY_PAGES = 5;

export function usesFiniteCodexSync(hostname: string): boolean {
  return hostname.toLowerCase().endsWith('.trycloudflare.com');
}

export function prependCodexHistoryPage(
  current: CodexThreadHistory,
  older: CodexThreadHistory,
): CodexThreadHistory {
  if (current.thread_id !== older.thread_id) {
    throw new Error('Codex history pagination returned the wrong thread');
  }
  const seen = new Set<string>();
  const messages = [...older.messages, ...current.messages].filter((message) => {
    if (seen.has(message.message_id)) return false;
    seen.add(message.message_id);
    return true;
  });
  return {
    thread_id: current.thread_id,
    messages,
    complete: older.complete,
    next_cursor: older.next_cursor,
  };
}
