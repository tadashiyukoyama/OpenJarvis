import type { ReactNode } from 'react';

export interface SendBlueWizardStep {
  title: string;
  content: ReactNode;
  canAdvance: boolean;
}

export function SendBlueWizardStepPanel({
  step,
  steps,
  error,
  loading,
  onBack,
  onNext,
  onFinish,
}: {
  step: number;
  steps: SendBlueWizardStep[];
  error: string;
  loading: boolean;
  onBack: () => void;
  onNext: () => void;
  onFinish: () => void;
}) {
  const current = steps[step];
  return (
    <div style={{ borderTop: '1px solid var(--color-border)', padding: 14 }}>
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        {steps.map((item, index) => (
          <div
            key={item.title}
            style={{
              flex: 1,
              height: 3,
              borderRadius: 2,
              background: index <= step
                ? 'var(--color-accent-purple)'
                : 'var(--color-border)',
            }}
          />
        ))}
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
        {current?.title}
      </div>
      {current?.content}
      {error && (
        <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
          {error}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        {step > 0 && (
          <button
            onClick={onBack}
            style={{
              fontSize: 12,
              padding: '6px 16px',
              background: 'var(--color-bg)',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 5,
              cursor: 'pointer',
            }}
          >
            Back
          </button>
        )}
        {step < steps.length - 1 ? (
          <button
            onClick={onNext}
            disabled={!current?.canAdvance}
            style={{
              fontSize: 12,
              padding: '6px 16px',
              background: 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)',
              border: 'none',
              borderRadius: 5,
              cursor: 'pointer',
              fontWeight: 600,
              opacity: current?.canAdvance ? 1 : 0.5,
            }}
          >
            Next
          </button>
        ) : (
          <button
            onClick={onFinish}
            disabled={loading || !current?.canAdvance}
            style={{
              fontSize: 12,
              padding: '6px 16px',
              background: 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)',
              border: 'none',
              borderRadius: 5,
              cursor: 'pointer',
              fontWeight: 600,
              opacity: loading || !current?.canAdvance ? 0.5 : 1,
            }}
          >
            {loading ? 'Connecting...' : 'Connect'}
          </button>
        )}
      </div>
    </div>
  );
}
