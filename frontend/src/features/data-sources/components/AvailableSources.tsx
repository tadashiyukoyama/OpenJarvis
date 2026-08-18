import type { CachedConnector } from '@/lib/store';
import type { ConnectRequest } from '@/types/connectors';
import { sourceMeta } from '../source-model';
import { InlineConnectForm, UploadForm } from './ConnectForms';

export function AvailableSources({
  sources,
  expandedId,
  loading,
  connectingId,
  connectStage,
  connectError,
  onToggle,
  onConnect,
  onRefresh,
}: {
  sources: CachedConnector[];
  expandedId: string | null;
  loading: boolean;
  connectingId: string | null;
  connectStage: string;
  connectError: string;
  onToggle: (id: string | null) => void;
  onConnect: (id: string, request: ConnectRequest) => void;
  onRefresh: () => void;
}) {
  if (!sources.length) return null;
  return (
    <section>
      <div className="hud-label mb-2 flex items-center gap-2">
        <span
          style={{
            display: 'inline-block', width: 6, height: 6,
            borderRadius: 999, background: 'var(--color-text-tertiary)',
          }}
        />
        Available · {sources.length}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {sources.map((source) => {
          const meta = sourceMeta(source.connector_id);
          const expanded = expandedId === source.connector_id;
          return (
            <div
              key={source.connector_id}
              className="hud-panel"
              style={{
                gridColumn: expanded ? '1 / -1' : undefined,
                opacity: expanded ? 1 : 0.85,
                borderStyle: expanded ? 'solid' : 'dashed',
              }}
            >
              <div
                style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }}
                onClick={() => onToggle(expanded ? null : source.connector_id)}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="font-semibold" style={{ fontSize: 14, color: 'var(--color-text)' }}>
                    {meta?.display_name ?? source.display_name}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
                    {meta?.description ?? 'Not connected'}
                  </div>
                </div>
                <span style={{ color: 'var(--color-text-secondary)', fontSize: 12, fontWeight: 500 }}>
                  {expanded ? '× Close' : '+ Add'}
                </span>
              </div>
              {expanded && source.connector_id === 'upload' && (
                <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                  <p style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
                    Paste text or upload supported files to add them to your knowledge base.
                  </p>
                  <UploadForm onDone={onRefresh} />
                </div>
              )}
              {expanded && source.connector_id !== 'upload' && meta?.steps && (
                <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                  {meta.steps.map((step, index) => (
                    <div
                      key={`${source.connector_id}-${index}`}
                      style={{
                        background: 'var(--color-bg)', border: '1px solid var(--color-border)',
                        borderRadius: 6, padding: 10, marginBottom: 8,
                      }}
                    >
                      <div style={{ color: 'var(--color-accent-purple)', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
                        STEP {index + 1}
                      </div>
                      <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>{step.label}</div>
                      {step.url && (
                        <a href={step.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', fontSize: 11 }}>
                          {step.urlLabel || 'Open'} →
                        </a>
                      )}
                    </div>
                  ))}
                  {meta.inputFields && (
                    <InlineConnectForm
                      fields={meta.inputFields}
                      loading={loading && connectingId === source.connector_id}
                      onSubmit={(request) => onConnect(source.connector_id, request)}
                    />
                  )}
                  {meta.troubleshooting && (
                    <details className="mt-2">
                      <summary className="text-[11px] cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}>
                        Having trouble?
                      </summary>
                      <ul className="mt-1 space-y-1">
                        {meta.troubleshooting.map((tip, index) => (
                          <li key={index} className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>{tip}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {connectingId === source.connector_id && connectStage && (
                    <div style={{ marginTop: 8, fontSize: 12, color: 'var(--color-warning)' }}>
                      {connectStage}
                    </div>
                  )}
                  {connectError && connectingId === null && expandedId === source.connector_id && (
                    <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
                      {connectError}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
