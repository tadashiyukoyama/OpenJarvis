import { useCallback, useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import {
  fetchWhatsAppQr,
  resetWhatsAppQr,
  startWhatsAppQr,
  type WhatsAppBaileysQrResponse,
  type WhatsAppBaileysStatus,
  type WhatsAppBaileysStatusResponse,
} from '../../lib/jarvis-sources-api';
import { WhatsAppQrMonitor } from '../../lib/whatsapp-qr-monitor';
import {
  describeWhatsAppStatus,
  isWhatsAppTerminalFailure,
} from '../../lib/whatsapp-baileys-status';

export function WhatsAppBaileysPanel() {
  const [status, setStatus] = useState<WhatsAppBaileysStatus>('disconnected');
  const [qrDataUrl, setQrDataUrl] = useState('');
  const [visibleGeneration, setVisibleGeneration] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const monitorRef = useRef<WhatsAppQrMonitor | null>(null);
  const qrRenderToken = useRef(0);
  const lastQrGeneration = useRef(-1);
  const lastQrPayload = useRef('');

  const applyStatus = useCallback((current: WhatsAppBaileysStatusResponse) => {
    setStatus(current.status);
    if (current.status === 'connected' || isWhatsAppTerminalFailure(current.status)) {
      qrRenderToken.current += 1;
      lastQrGeneration.current = -1;
      lastQrPayload.current = '';
      setQrDataUrl('');
      setVisibleGeneration(0);
    }
    if (isWhatsAppTerminalFailure(current.status)) {
      setError(describeWhatsAppStatus(current).message);
    } else if (current.last_error) {
      setError(current.last_error);
    } else {
      setError('');
    }
    return current;
  }, []);

  const applyQrSnapshot = useCallback((response: WhatsAppBaileysQrResponse) => {
    applyStatus(response);
    if (!response.available || !response.qr) {
      qrRenderToken.current += 1;
      lastQrPayload.current = '';
      setQrDataUrl('');
      setVisibleGeneration(0);
      return;
    }

    if (
      lastQrGeneration.current === response.qr_generation
      && lastQrPayload.current === response.qr
    ) {
      return;
    }

    lastQrGeneration.current = response.qr_generation;
    lastQrPayload.current = response.qr;
    const renderToken = ++qrRenderToken.current;
    setQrDataUrl('');
    setVisibleGeneration(response.qr_generation);
    void QRCode.toDataURL(response.qr, {
      errorCorrectionLevel: 'M',
      margin: 2,
      width: 280,
    }).then((dataUrl) => {
      if (renderToken === qrRenderToken.current) setQrDataUrl(dataUrl);
    }).catch((cause) => {
      if (renderToken !== qrRenderToken.current) return;
      setError(cause instanceof Error ? cause.message : 'Falha ao renderizar o QR Code.');
    });
  }, [applyStatus]);

  useEffect(() => {
    const monitor = new WhatsAppQrMonitor({
      fetchSnapshot: fetchWhatsAppQr,
      onSnapshot: applyQrSnapshot,
      onError: (cause) => {
        qrRenderToken.current += 1;
        lastQrGeneration.current = -1;
        lastQrPayload.current = '';
        setQrDataUrl('');
        setVisibleGeneration(0);
        setStatus('error');
        setError(cause instanceof Error ? cause.message : 'Falha ao atualizar o QR Code.');
      },
    });
    monitorRef.current = monitor;
    monitor.start();
    return () => {
      monitor.stop();
      if (monitorRef.current === monitor) monitorRef.current = null;
      qrRenderToken.current += 1;
      lastQrPayload.current = '';
    };
  }, [applyQrSnapshot]);

  const beginConnection = async () => {
    setBusy(true);
    setError('');
    setQrDataUrl('');
    try {
      const initial =
        status === 'logged_out' || status === 'auth_inconsistent'
          ? await resetWhatsAppQr()
          : await startWhatsAppQr();
      applyStatus(initial);
      monitorRef.current?.start();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Falha ao iniciar o bridge Baileys.');
      setStatus('error');
    } finally {
      setBusy(false);
    }
  };

  const presentation = describeWhatsAppStatus({ status, last_error: null });
  const pairing = status === 'connecting' || status === 'qr_required';
  const buttonDisabled = busy || pairing || status === 'connected';

  return (
    <div
      style={{
        marginTop: 14,
        padding: 12,
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        background: 'var(--color-bg)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600 }}>Baileys · QR Code</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 3 }}>
            Conecte uma sessão WhatsApp local sem usar a API Meta.
          </div>
        </div>
        <span style={{ fontSize: 11, color: status === 'connected' ? 'var(--color-success)' : 'var(--color-text-secondary)' }}>
          {presentation.label}
        </span>
      </div>

      {qrDataUrl && status !== 'connected' && (
        <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <div style={{ background: '#fff', padding: 8, borderRadius: 6 }}>
            <img src={qrDataUrl} alt="QR Code para conectar o WhatsApp via Baileys" width={280} height={280} />
          </div>
          <div style={{ maxWidth: 260, fontSize: 11, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
            No WhatsApp, abra <strong>Dispositivos conectados</strong>, toque em{' '}
            <strong>Conectar dispositivo</strong> e leia este código. O QR é renovado automaticamente enquanto a tela estiver aberta.
            {visibleGeneration > 0 && (
              <div style={{ marginTop: 6 }}>QR atual · geração {visibleGeneration}</div>
            )}
          </div>
        </div>
      )}

      {status === 'connected' && (
        <div
          role="status"
          style={{ marginTop: 10, fontSize: 11, color: 'var(--color-success)' }}
        >
          {presentation.message}
        </div>
      )}

      {error && <div style={{ marginTop: 10, fontSize: 11, color: 'var(--color-error)' }}>{error}</div>}

      <button
        type="button"
        onClick={() => void beginConnection()}
        disabled={buttonDisabled}
        style={{
          marginTop: 12,
          padding: '8px 12px',
          border: '1px solid var(--color-accent)',
          borderRadius: 6,
          background: buttonDisabled ? 'var(--color-disabled-bg)' : 'transparent',
          color: 'var(--color-text)',
          fontSize: 12,
          cursor: buttonDisabled ? 'default' : 'pointer',
        }}
      >
        {busy && status === 'disconnected'
          ? 'Iniciando bridge…'
          : presentation.retryLabel}
      </button>
    </div>
  );
}
