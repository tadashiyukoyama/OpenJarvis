import { describe, expect, it } from 'vitest';
import type { JarvisAgentEvent } from '../api/types';
import { agentEventView } from './events';

function event(
  eventType: string,
  payload: Record<string, unknown>,
): JarvisAgentEvent {
  return {
    sequence: 1,
    event_id: 'event-1',
    event_type: eventType,
    session_id: 'session-1',
    action_id: null,
    job_id: null,
    payload,
    created_at: 1,
  };
}

describe('Jarvis canonical event presentation', () => {
  it('shows a rejected tool call as an error with its stable code', () => {
    expect(agentEventView(event('tool_call_rejected', {
      requested_name: 'codex_get_status',
      code: 'TOOL_INTENT_MISMATCH',
    }))).toEqual({
      type: 'error',
      text: 'codex_get_status · TOOL_INTENT_MISMATCH',
    });
  });

  it('shows the exact canonical tool on dispatch completion', () => {
    expect(agentEventView(event('dispatch_completed', {
      tool_id: 'codex.status',
      summary: 'Codex conectado.',
    }))).toEqual({
      type: 'dispatch',
      text: 'codex.status · Codex conectado.',
    });
  });
});
