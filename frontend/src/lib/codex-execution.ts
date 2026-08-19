import type { CodexThreadExecutionEvent } from '../types';

const TERMINAL_STATES = new Set([
  'completed',
  'failed',
  'interrupted',
  'cancelled',
  'unknown',
]);

export function isTerminalCodexExecution(event: CodexThreadExecutionEvent): boolean {
  return TERMINAL_STATES.has(event.state);
}

export function codexExecutionPhase(event: CodexThreadExecutionEvent): string {
  if (event.action_summary?.trim()) return event.action_summary.trim();
  switch (event.state) {
    case 'starting':
      return 'Codex iniciando...';
    case 'running':
    case 'working':
      return 'Codex executando...';
    case 'completed':
      return 'Codex finalizando...';
    case 'failed':
      return 'A execução do Codex falhou.';
    case 'interrupted':
      return 'A execução do Codex foi interrompida.';
    case 'cancelled':
      return 'A execução do Codex foi cancelada.';
    default:
      return 'O estado da execução do Codex é desconhecido.';
  }
}
