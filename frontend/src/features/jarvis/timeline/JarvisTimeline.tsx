import { Activity, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import type { JarvisTimelineEntry } from './types';

export function JarvisTimeline({ entries }: { entries: JarvisTimelineEntry[] }) {
  return (
    <aside className="jarvis-panel jarvis-timeline-panel">
      <div className="jarvis-panel-title"><Activity size={15} /> LINHA OPERACIONAL</div>
      <div className="jarvis-timeline">
        {entries.length === 0 && (
          <div className="jarvis-empty-timeline">Os eventos da sessão aparecerão aqui.</div>
        )}
        {[...entries].reverse().map((entry) => (
          <div className={`jarvis-event event-${entry.type}`} key={entry.id}>
            <span className="jarvis-event-icon">
              {entry.type === 'error'
                ? <XCircle />
                : entry.type === 'approval'
                  ? <AlertTriangle />
                  : <CheckCircle2 />}
            </span>
            <div>
              <time>{new Date(entry.time).toLocaleTimeString('pt-BR')}</time>
              <p>{entry.text}</p>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
