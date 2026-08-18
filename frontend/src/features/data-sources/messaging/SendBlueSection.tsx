import { useEffect, useState } from 'react';
import {
  bindAgentChannel,
  sendblueHealth,
  sendblueRegisterWebhook,
} from '@/lib/api';
import type { ChannelBinding } from '@/lib/api';
import {
  SendBlueConnectedCard,
  type SendBlueHealth,
} from './SendBlueConnectedCard';
import {
  SendBlueWizardStepPanel,
  type SendBlueWizardStep,
} from './SendBlueWizardStepPanel';

export function SendBlueSection({
  agentId,
  binding,
  onDone,
  onRemove,
}: {
  agentId: string;
  binding?: ChannelBinding;
  onDone: () => void;
  onRemove: (id: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [phone, setPhone] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookStatus, setWebhookStatus] = useState<'idle' | 'registering' | 'done' | 'error'>('idle');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [health, setHealth] = useState<SendBlueHealth | null>(null);

  useEffect(() => {
    if (binding) {
      sendblueHealth().then(setHealth).catch(() => {});
    }
  }, [agentId, binding]);

  const registerWebhook = async () => {
    if (!webhookUrl.trim()) return;
    setWebhookStatus('registering');
    try {
      const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
      await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
      setWebhookStatus('done');
    } catch {
      setWebhookStatus('error');
    }
  };

  if (binding) {
    return (
      <SendBlueConnectedCard
        binding={binding}
        health={health}
        onRemove={onRemove}
      />
    );
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg)', border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)', fontSize: 12,
    boxSizing: 'border-box',
  };

  // Not active — setup wizard
  const steps: SendBlueWizardStep[] = [
    {
      title: 'Get SendBlue API keys',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            SendBlue lets your agent send and receive iMessages and SMS. You need an account and API credentials.
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <a
              href="https://sendblue.co"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              1. Sign up at sendblue.co &rarr;
            </a>
          </div>
          <div style={{ marginBottom: 8 }}>
            <a
              href="https://dashboard.sendblue.co/api-credentials"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              2. Go to your API Credentials page &rarr;
            </a>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
            Copy the "API Key" and "API Secret" from the credentials page and paste them below.
          </div>
          <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
            placeholder="API Key" style={{ ...inputStyle, marginTop: 4 }} />
          <input value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
            placeholder="API Secret" type="password" style={{ ...inputStyle, marginTop: 4 }} />
        </div>
      ),
      canAdvance: Boolean(apiKey.trim() && apiSecret.trim()),
    },
    {
      title: 'Enter your phone number',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            Which phone number should SendBlue use? This is the number people will text to reach your agent.
          </div>
          <input value={phone} onChange={(e) => setPhone(e.target.value)}
            placeholder="+1XXXXXXXXXX" style={inputStyle} />
        </div>
      ),
      canAdvance: phone.trim().length >= 10,
    },
    {
      title: 'Set up webhook (ngrok tunnel)',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            SendBlue needs a public URL to send incoming messages to your local server. Use ngrok to create a tunnel.
          </div>
          <div style={{
            fontSize: 11, lineHeight: 1.6,
            color: 'var(--color-text-secondary)',
            padding: '8px 10px', marginBottom: 10,
            background: 'var(--color-bg-secondary)',
            borderRadius: 6,
            borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
          }}>
            <div><strong>1.</strong> Open a terminal and run: <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>ngrok http 8000</code></div>
            <div style={{ marginTop: 4 }}><strong>2.</strong> Copy the <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>https://</code> forwarding URL (e.g. https://abc123.ngrok.io)</div>
            <div style={{ marginTop: 4 }}><strong>3.</strong> Paste it below and click "Register Webhook"</div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={webhookUrl}
              onChange={(e) => { setWebhookUrl(e.target.value); setWebhookStatus('idle'); }}
              placeholder="https://abc123.ngrok-free.app"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={registerWebhook}
              disabled={!webhookUrl.trim() || webhookStatus === 'registering'}
              style={{
                fontSize: 11, padding: '6px 12px', whiteSpace: 'nowrap',
                background: webhookStatus === 'done' ? 'var(--color-success)' : 'var(--color-accent-purple)',
                color: 'var(--color-on-accent)', border: 'none', borderRadius: 4,
                cursor: 'pointer', fontWeight: 600,
                opacity: !webhookUrl.trim() || webhookStatus === 'registering' ? 0.5 : 1,
              }}
            >
              {webhookStatus === 'registering' ? 'Registering...'
                : webhookStatus === 'done' ? 'Registered!'
                : webhookStatus === 'error' ? 'Retry'
                : 'Register Webhook'}
            </button>
          </div>
          {webhookStatus === 'done' && (
            <div style={{ fontSize: 11, color: 'var(--color-success)', marginTop: 6 }}>
              Webhook registered! Incoming texts will be forwarded to your agent.
            </div>
          )}
          {webhookStatus === 'error' && (
            <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
              Failed to register webhook. Check your ngrok URL and SendBlue credentials.
            </div>
          )}
          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
            Don't have ngrok? <a href="https://ngrok.com/download" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>Download it free</a>. You can also skip this step and register the webhook later.
          </div>
        </div>
      ),
      canAdvance: true, // webhook is optional — user can skip
    },
  ];

  const handleFinish = async () => {
    setLoading(true);
    setError('');
    try {
      await bindAgentChannel(agentId, 'sendblue', {
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
        phone_number: phone.trim(),
      });
      // If webhook was registered in the wizard, that's already done.
      // If not, try a best-effort registration with the provided URL.
      if (webhookUrl.trim() && webhookStatus !== 'done') {
        try {
          const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
          await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
        } catch { /* */ }
      }
      onDone();
      setStep(0);
      setApiKey('');
      setApiSecret('');
      setPhone('');
      setWebhookUrl('');
      setWebhookStatus('idle');
    } catch (err: any) {
      setError(err.message || 'Failed to connect');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: 'var(--color-bg-secondary)',
      border: '1px dashed var(--color-border)',
      borderRadius: 8, marginBottom: 10,
      overflow: 'hidden',
    }}>
      <div
        style={{
          display: 'flex', alignItems: 'center',
          padding: '12px 14px', cursor: 'pointer',
        }}
        onClick={() => setStep(step === 0 && !apiKey ? -1 : 0)}
      >
        <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS (SendBlue)</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
            Let people text your agent from any phone
          </div>
        </div>
        <span style={{ color: 'var(--color-accent-purple)', fontSize: 11, fontWeight: 500 }}>
          {step >= 0 ? 'Set Up' : '+ Add'}
        </span>
      </div>

      {step >= 0 && (
        <SendBlueWizardStepPanel
          step={step}
          steps={steps}
          error={error}
          loading={loading}
          onBack={() => setStep(step - 1)}
          onNext={() => setStep(step + 1)}
          onFinish={handleFinish}
        />
      )}
    </div>
  );
}
