import { describe, expect, it } from 'vitest';
import type { CodexThreadExecutionEvent } from '../types';
import { codexExecutionPhase, isTerminalCodexExecution } from './codex-execution';

function event(
  overrides: Partial<CodexThreadExecutionEvent> = {},
): CodexThreadExecutionEvent {
  return {
    thread_id: 'thread-a',
    turn_id: 'turn-1',
    item_id: null,
    event_type: 'turn_started',
    state: 'running',
    ...overrides,
  };
}

describe('Codex execution presentation', () => {
  it('uses only the sanitized action summary when it is available', () => {
    expect(codexExecutionPhase(event({ action_summary: 'Executando testes.' }))).toBe(
      'Executando testes.',
    );
  });

  it('classifies active and terminal states without guessing completion', () => {
    expect(isTerminalCodexExecution(event({ state: 'running' }))).toBe(false);
    expect(isTerminalCodexExecution(event({ state: 'completed' }))).toBe(true);
    expect(codexExecutionPhase(event({ state: 'unknown' }))).toContain('desconhecido');
  });
});
