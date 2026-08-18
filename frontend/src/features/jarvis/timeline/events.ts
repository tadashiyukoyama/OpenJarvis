import type { JarvisOperationalEventType } from '@/lib/jarvis-api';
import type { JarvisAgentEvent } from '../api/types';

export function agentEventView(event: JarvisAgentEvent): {
  type: JarvisOperationalEventType;
  text: string;
} {
  const summary = typeof event.payload.summary === 'string' ? event.payload.summary : '';
  const code = typeof event.payload.code === 'string' ? event.payload.code : '';
  const state = typeof event.payload.state === 'string' ? event.payload.state : '';
  const tool = typeof event.payload.tool_id === 'string' ? event.payload.tool_id : '';
  const details = [tool, state, code, summary].filter(Boolean).join(' · ');
  if (event.event_type.includes('failed')) {
    return { type: 'error', text: details || event.event_type };
  }
  if (event.event_type.startsWith('confirmation')) {
    return { type: 'approval', text: details || event.event_type };
  }
  if (event.event_type.startsWith('dispatch') || event.event_type.startsWith('job')) {
    return {
      type: event.event_type === 'job_completed' ? 'codex' : 'dispatch',
      text: details || event.event_type,
    };
  }
  return { type: 'system', text: details || event.event_type };
}
