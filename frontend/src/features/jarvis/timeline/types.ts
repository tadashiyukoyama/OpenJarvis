import type { JarvisOperationalEventType } from '@/lib/jarvis-api';

export interface JarvisTimelineEntry {
  id: string;
  type: JarvisOperationalEventType;
  text: string;
  time: number;
}
