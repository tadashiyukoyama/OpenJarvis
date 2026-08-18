import { useState } from 'react';
import type { ConnectRequest } from '@/types/connectors';
import { InlineConnectForm } from './ConnectForms';

export function GmailOAuthAdvanced({
  loading,
  onConnect,
}: {
  loading: boolean;
  onConnect: (req: ConnectRequest) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 12 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          background: 'transparent',
          border: 'none',
          padding: 0,
          fontSize: 11,
          color: 'var(--color-text-tertiary)',
          cursor: 'pointer',
          textDecoration: 'underline',
        }}
      >
        {open ? 'Hide advanced' : 'Advanced: Connect with Google OAuth'}
      </button>
      {open && (
        <div
          style={{
            marginTop: 8,
            padding: 10,
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
            For developers with an existing Google Cloud project. Enable the
            Gmail API and create a Desktop OAuth client at{' '}
            <a
              href="https://console.cloud.google.com/apis/credentials"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}
            >
              Google Cloud Credentials →
            </a>{' '}
            then paste the Client ID and Client Secret below.
          </div>
          <InlineConnectForm
            fields={[
              { name: 'email', placeholder: 'Client ID', type: 'text' },
              { name: 'password', placeholder: 'Client Secret', type: 'password' },
            ]}
            loading={loading}
            onSubmit={onConnect}
          />
        </div>
      )}
    </div>
  );
}
