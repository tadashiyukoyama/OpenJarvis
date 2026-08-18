import type { ChannelBinding } from '@/lib/api';

export interface SendBlueHealth {
  channel_connected: boolean;
  bridge_wired: boolean;
  ready: boolean;
  webhook_registered?: boolean;
  phone_number?: string;
}

export function SendBlueConnectedCard({
  binding,
  health,
  onRemove,
}: {
  binding: ChannelBinding;
  health: SendBlueHealth | null;
  onRemove: (id: string) => void;
}) {
  const config = (binding.config || {}) as Record<string, unknown>;
  return (
    <div
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
        borderRadius: 8,
        marginBottom: 10,
        overflow: 'hidden',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
        <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS</div>
          <div style={{ fontSize: 11, color: 'var(--color-success)' }}>
            Active &mdash; text {(config.phone_number as string) || 'your number'} to chat
          </div>
        </div>
        <button
          onClick={() => onRemove(binding.id)}
          style={{
            fontSize: 10,
            padding: '2px 8px',
            background: 'transparent',
            color: 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          Remove
        </button>
      </div>
      {health && (
        <div
          style={{
            borderTop: '1px solid var(--color-border)',
            padding: '8px 14px',
            fontSize: 11,
            color: 'var(--color-text-secondary)',
          }}
        >
          Webhook: {health.webhook_registered ? 'registered' : 'not registered'}
          {health.phone_number && ` \u2022 ${health.phone_number}`}
        </div>
      )}
    </div>
  );
}
