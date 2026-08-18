import { describe, expect, it } from 'vitest';
import { operationalCorrelation, safeOperationalEventText } from './jarvis-observability';

describe('Jarvis operational observability', () => {
  it('keeps private conversation payloads out of the durable event text', () => {
    expect(safeOperationalEventText('user', 'mensagem privada')).toBe(
      'user_payload length=16',
    );
    expect(safeOperationalEventText('codex', 'resposta confidencial')).toBe(
      'codex_payload length=21',
    );
  });

  it('preserves safe structured lifecycle events', () => {
    expect(safeOperationalEventText('session', 'session_closed session_id=abc')).toBe(
      'session_closed session_id=abc',
    );
  });

  it('keeps safe approval correlation while dropping unapproved fields', () => {
    expect(
      safeOperationalEventText(
        'approval',
        'confirmation_not_created function_call_id=call-1 reason=route_mismatch command=private',
      ),
    ).toBe(
      'confirmation_not_created function_call_id=call-1 reason=route_mismatch',
    );
    expect(safeOperationalEventText('approval', 'Autorizar mensagem privada')).toBe(
      'approval_payload length=26',
    );
  });

  it('sanitizes the function call id in a correlation record', () => {
    expect(operationalCorrelation('request-1', 'comando', 'abc123', 'call with spaces'))
      .toContain('function_call_id=call_with_spaces');
  });
});
