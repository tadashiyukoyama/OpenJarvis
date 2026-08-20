import { useCallback, useEffect, useRef, useState } from 'react';
import {
  appendJarvisOperationalEvent,
  fetchJarvisOperationalEvents,
  type JarvisOperationalEvent,
  type JarvisOperationalEventType,
} from '@/lib/jarvis-api';
import { safeOperationalEventText } from '@/lib/jarvis-observability';
import { fetchJarvisAgentThreadEvents } from '../api/client';
import { agentEventView } from './events';
import type { JarvisTimelineEntry } from './types';

const MAX_TIMELINE_ENTRIES = 50;

interface TimelineTarget {
  threadId: string;
  projectCwd: string;
}

interface TimelineOptions {
  eventId?: string;
  time?: number;
  persist?: boolean;
}

function timelineId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function operationalEventToTimeline(
  event: JarvisOperationalEvent,
): JarvisTimelineEntry {
  return {
    id: event.event_id,
    type: event.event_type,
    text: event.text,
    time: event.occurred_at,
  };
}

export function mergeTimelineEntries(
  persisted: JarvisTimelineEntry[],
  current: JarvisTimelineEntry[],
): JarvisTimelineEntry[] {
  const merged = new Map(persisted.map((entry) => [entry.id, entry]));
  for (const entry of current) merged.set(entry.id, entry);
  return [...merged.values()]
    .sort((left, right) => left.time - right.time || left.id.localeCompare(right.id))
    .slice(-MAX_TIMELINE_ENTRIES);
}

export function usePersistentJarvisTimeline(target: TimelineTarget | null) {
  const [timeline, setTimeline] = useState<JarvisTimelineEntry[]>([]);
  const targetRef = useRef<TimelineTarget | null>(target);
  targetRef.current = target;

  useEffect(() => {
    const controller = new AbortController();
    if (!target?.threadId) {
      setTimeline([]);
      return () => controller.abort();
    }
    setTimeline([]);
    void Promise.all([
      fetchJarvisOperationalEvents(target.threadId, MAX_TIMELINE_ENTRIES, controller.signal),
      fetchJarvisAgentThreadEvents(
        target.projectCwd,
        target.threadId,
        MAX_TIMELINE_ENTRIES,
        controller.signal,
      ),
    ])
      .then(([operationalEvents, agentEvents]) => {
        if (controller.signal.aborted) return;
        const persisted = [
          ...operationalEvents.map(operationalEventToTimeline),
          ...agentEvents.map((event) => {
            const view = agentEventView(event);
            return {
              id: event.event_id,
              type: view.type,
              text: view.text,
              time: event.created_at * 1_000,
            };
          }),
        ];
        setTimeline((current) => mergeTimelineEntries(persisted, current));
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setTimeline((current) => mergeTimelineEntries(current, [{
          id: timelineId(),
          type: 'error',
          text: error instanceof Error ? error.message : 'Histórico operacional indisponível.',
          time: Date.now(),
        }]));
      });
    return () => controller.abort();
  }, [target?.projectCwd, target?.threadId]);

  const addTimeline = useCallback((
    type: JarvisOperationalEventType,
    text: string,
    options: TimelineOptions = {},
  ) => {
    const entry: JarvisTimelineEntry = {
      id: options.eventId ?? timelineId(),
      type,
      text,
      time: options.time ?? Date.now(),
    };
    setTimeline((current) => mergeTimelineEntries(current, [entry]));
    const selected = targetRef.current;
    if (!selected?.threadId || options.persist === false) return;
    void appendJarvisOperationalEvent({
      event_id: entry.id,
      thread_id: selected.threadId,
      project_cwd: selected.projectCwd,
      event_type: type,
      text: safeOperationalEventText(type, text),
      occurred_at: entry.time,
    }).catch(() => {
      setTimeline((current) => mergeTimelineEntries(current, [{
        id: timelineId(),
        type: 'error',
        text: 'Falha ao persistir a linha operacional.',
        time: Date.now(),
      }]));
    });
  }, []);

  return { timeline, addTimeline };
}

export const persistentTimelineInternals = { MAX_TIMELINE_ENTRIES, timelineId };
