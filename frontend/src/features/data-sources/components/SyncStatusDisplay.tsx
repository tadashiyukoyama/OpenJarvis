import { useState } from 'react';
import { triggerSync } from '@/lib/connectors-api';
import type { SyncStatus } from '@/types/connectors';

function formatTimeAgo(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const diffSec = (Date.now() - t) / 1000;
  if (diffSec < 30) return 'just now';
  if (diffSec < 60) return 'less than a min ago';
  if (diffSec < 3600) {
    const m = Math.round(diffSec / 60);
    return `${m} min${m === 1 ? '' : 's'} ago`;
  }
  if (diffSec < 86400) {
    const h = Math.round(diffSec / 3600);
    return `${h} hr${h === 1 ? '' : 's'} ago`;
  }
  const d = Math.round(diffSec / 86400);
  return `${d} day${d === 1 ? '' : 's'} ago`;
}
/** Render how far back the corpus extends, given the oldest indexed
 *  item's timestamp. Returns null when there isn't enough data yet. */
function formatBacklogRange(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const days = (Date.now() - t) / 86400_000;
  if (days < 7) return 'past few days';
  if (days < 30) return 'past month';
  if (days < 90) return 'past 3 months';
  if (days < 365) return 'past year';
  const years = Math.round(days / 365);
  return `past ${years} year${years === 1 ? '' : 's'}`;
}

export function SyncStatusDisplay({
  chunks,
  sync,
  unitLabel,
  connectorId,
  onSyncTriggered,
}: {
  chunks: number;
  sync: SyncStatus | undefined;
  unitLabel: string;
  connectorId: string;
  onSyncTriggered: () => void;
}) {
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState('');

  const handleSync = async () => {
    setSyncing(true);
    setSyncError('');
    try {
      await triggerSync(connectorId);
      onSyncTriggered();
    } catch (err: any) {
      setSyncError(err.message || 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  // Error state
  if (sync?.error) {
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-error)', marginBottom: 4 }}>
          Error: {sync.error}
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: 'pointer', fontWeight: 600,
            opacity: syncing ? 0.5 : 1,
          }}
        >{syncing ? 'Retrying...' : 'Retry Sync'}</button>
      </div>
    );
  }

  // Treat the SyncEngine's checkpointed items_synced as the source of
  // truth for "total indexed" — `chunks` from listConnectors counts
  // embedding chunks (often != source items) and the checkpoint is what
  // both the syncing and idle branches need to display consistently.
  const totalIndexed = sync?.items_synced ?? chunks;
  const itemsTotal = sync?.items_total ?? 0;
  const backlogRange = formatBacklogRange(sync?.oldest_item_date);
  // "Complete inbox" — the user has indexed everything reachable. Only
  // surface this label when idle (during a sync we always show how far
  // back we've gotten so far).
  const isComplete =
    totalIndexed > 0 && itemsTotal > 0 && totalIndexed >= itemsTotal;

  // Actively syncing — single status line + reassurance line.
  if (sync?.state === 'syncing' || syncing) {
    const rangeLabel = backlogRange ?? 'building corpus';
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--color-warning)', marginBottom: 4 }}>
          Indexed{' '}
          <span key={totalIndexed} className="sync-bump">
            {totalIndexed.toLocaleString()} {unitLabel}
          </span>{' '}
          <span style={{ color: 'var(--color-text-tertiary)' }}>
            ({rangeLabel})
          </span>{' '}
          <span style={{ color: 'var(--color-text-tertiary)' }}>
            · Still indexing…
          </span>
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--color-text-tertiary)' }}>
          Deep Research available now · results improve as more {unitLabel} are indexed
        </div>
      </div>
    );
  }

  // Idle — already has indexed items: show the corpus size + range or
  // "complete inbox" label, plus how long ago we last refreshed it.
  if (totalIndexed > 0) {
    const lastSyncLabel = formatTimeAgo(sync?.last_sync);
    const rangeLabel = isComplete
      ? 'complete inbox'
      : backlogRange;
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--color-success)' }}>
            Indexed {totalIndexed.toLocaleString()} {unitLabel}
            {rangeLabel && (
              <span style={{ color: 'var(--color-text-tertiary)' }}>
                {' '}({rangeLabel})
              </span>
            )}
            {lastSyncLabel && (
              <span style={{ color: 'var(--color-text-tertiary)' }}>
                {' · '}Last synced {lastSyncLabel}
              </span>
            )}
          </span>
          <button
            onClick={handleSync}
            disabled={syncing}
            style={{
              fontSize: 9, padding: '1px 6px',
              background: 'transparent',
              color: 'var(--color-text-tertiary)',
              border: '1px solid var(--color-border)',
              borderRadius: 3, cursor: 'pointer',
            }}
          >{syncing ? '...' : 'Re-sync'}</button>
        </div>
        {syncError && (
          <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
            {syncError}
          </div>
        )}
      </div>
    );
  }

  // Connected but nothing ever ingested. Mirror the original copy.
  const hasSynced = sync?.last_sync != null;
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          {hasSynced
            ? `Synced — 0 ${unitLabel} found`
            : 'Connected — not synced yet'}
        </span>
        <button
          onClick={handleSync}
          disabled={syncing}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: 'pointer', fontWeight: 600,
            opacity: syncing ? 0.5 : 1,
          }}
        >{syncing ? 'Syncing...' : hasSynced ? 'Re-sync' : 'Sync Now'}</button>
      </div>
      {hasSynced && connectorId === 'slack' && (
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
          Tip: invite the bot to channels with /invite @OpenJarvis, then re-sync
        </div>
      )}
      {syncError && (
        <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
          {syncError}
        </div>
      )}
    </div>
  );
}
