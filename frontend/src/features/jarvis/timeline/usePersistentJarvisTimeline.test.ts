import { describe, expect, it } from 'vitest';
import type { JarvisOperationalEvent } from '@/lib/jarvis-api';
import {
  mergeTimelineEntries,
  operationalEventToTimeline,
} from './usePersistentJarvisTimeline';

describe('persistent Jarvis timeline helpers', () => {
  it('hydrates a stored operational event without losing its identity', () => {
    const event: JarvisOperationalEvent = {
      event_id: 'event-1',
      thread_id: 'thread-1',
      project_cwd: 'D:/project',
      event_type: 'dispatch',
      text: 'codex.delegate · approval_required',
      occurred_at: 1_000,
    };

    expect(operationalEventToTimeline(event)).toEqual({
      id: 'event-1',
      type: 'dispatch',
      text: 'codex.delegate · approval_required',
      time: 1_000,
    });
  });

  it('deduplicates by event id and keeps the current richer view', () => {
    const result = mergeTimelineEntries(
      [{ id: 'same', type: 'user', text: 'user_payload length=10', time: 1_000 }],
      [{ id: 'same', type: 'user', text: 'texto visível na sessão', time: 1_000 }],
    );

    expect(result).toEqual([
      { id: 'same', type: 'user', text: 'texto visível na sessão', time: 1_000 },
    ]);
  });

  it('keeps only the latest fifty ordered events', () => {
    const values = Array.from({ length: 55 }, (_, index) => ({
      id: `event-${index.toString().padStart(2, '0')}`,
      type: 'system' as const,
      text: String(index),
      time: index,
    }));

    const result = mergeTimelineEntries(values, []);
    expect(result).toHaveLength(50);
    expect(result[0].text).toBe('5');
    expect(result[result.length - 1]?.text).toBe('54');
  });
});
