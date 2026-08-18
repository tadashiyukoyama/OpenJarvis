import type { CachedConnector } from '@/lib/store';
import type { SyncStatus } from '@/types/connectors';
import { sourceMeta } from '../source-model';
import { SyncStatusDisplay } from './SyncStatusDisplay';

export function ConnectedSources({
  sources,
  statuses,
  disconnectingId,
  onDisconnect,
  onRefresh,
}: {
  sources: CachedConnector[];
  statuses: Record<string, SyncStatus>;
  disconnectingId: string | null;
  onDisconnect: (id: string) => void;
  onRefresh: () => void;
}) {
  if (!sources.length) return null;
  return (
    <section>
      <div className="hud-label mb-2 flex items-center gap-2">
        <span
          style={{
            display: 'inline-block', width: 6, height: 6,
            borderRadius: 999, background: 'var(--color-success)',
          }}
        />
        Connected · {sources.length}
      </div>
      <div className="flex flex-col gap-2">
        {sources.map((source) => {
          const meta = sourceMeta(source.connector_id);
          const sync = statuses[source.connector_id];
          return (
            <div
              key={source.connector_id}
              className="hud-panel"
              style={{
                borderColor: sync?.error
                  ? 'color-mix(in srgb, var(--color-error) 28%, transparent)'
                  : 'var(--color-border)',
              }}
            >
              <div style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="font-semibold" style={{ fontSize: 14, color: 'var(--color-text)' }}>
                    {meta?.display_name ?? source.display_name}
                  </div>
                  <SyncStatusDisplay
                    chunks={source.chunks}
                    sync={sync}
                    unitLabel={meta?.unitLabel || 'items'}
                    connectorId={source.connector_id}
                    onSyncTriggered={onRefresh}
                  />
                </div>
                <button
                  onClick={() => onDisconnect(source.connector_id)}
                  disabled={disconnectingId === source.connector_id}
                  className="hud-label"
                  style={{
                    padding: '6px 12px', background: 'transparent',
                    color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)',
                    borderRadius: 4, cursor: 'pointer', letterSpacing: '0.15em',
                    opacity: disconnectingId === source.connector_id ? 0.5 : 1,
                  }}
                >
                  {disconnectingId === source.connector_id ? 'Disconnecting…' : 'Disconnect'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
