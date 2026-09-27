import { useCallback, useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import {
  fetchEvolutionQr,
  fetchEvolutionStatus,
  provisionEvolution,
  type EvolutionWhatsAppQr,
  type EvolutionWhatsAppStatus,
} from '../../lib/evolution-api';

function describe(state: EvolutionWhatsAppStatus | null): string {
  if (!state) return 'Consultando Evolution API…';
  if (!state.configured) return 'Evolution API não configurada';
  if (state.state === 'not_provisioned') return 'Sessão ainda não criada';
  if (state.connected) return 'WhatsApp conectado';
  if (state.state === 'unavailable') return 'Evolution API indisponível';
  return `Estado: ${state.state}`;
}

export function EvolutionWhatsAppPanel() {
  const [status, setStatus] = useState<EvolutionWhatsAppStatus | null>(null);
  const [qr, setQr] = useState<EvolutionWhatsAppQr | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [provisioning, setProvisioning] = useState(false);
  const [error, setError] = useState('');
  const renderToken = useRef(0);

  const refreshStatus = useCallback(async () => {
    try {
      const current = await fetchEvolutionStatus();
      setStatus(current);
      if (current.connected) {
        renderToken.current += 1;
        setQrDataUrl('');
        setQr(null);
      }
      setError(current.error_code || '');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Falha ao consultar Evolution API.');
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const interval = window.setInterval(() => void refreshStatus(), 10_000);
    return () => window.clearInterval(interval);
  }, [refreshStatus]);

  const showQr = async () => {
    setBusy(true);
    setError('');
    try {
      const current = await fetchEvolutionQr();
      setQr(current);
      if (!current.available) {
        setQrDataUrl('');
        setError(current.error_code || 'QR ainda não disponível.');
        return;
      }
      if (current.base64) {
        setQrDataUrl(current.base64.startsWith('data:') ? current.base64 : `data:image/png;base64,${current.base64}`);
        return;
      }
      if (current.qr) {
        const token = ++renderToken.current;
        const image = await QRCode.toDataURL(current.qr, { errorCorrectionLevel: 'M', margin: 2, width: 280 });
        if (token === renderToken.current) setQrDataUrl(image);
      }
    } catch (cause) {
      setQrDataUrl('');
      setError(cause instanceof Error ? cause.message : 'Falha ao carregar QR da Evolution API.');
    } finally {
      setBusy(false);
    }
  };

  const createInstance = async () => {
    setProvisioning(true);
    setError('');
    try {
      const result = await provisionEvolution();
      if (!result.provisioned && result.error_code) {
        setError(result.error_code);
      }
      await refreshStatus();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Falha ao criar a sessão Evolution.');
    } finally {
      setProvisioning(false);
    }
  };

  const canRequestQr = Boolean(status?.configured && status.instance_exists && !status.connected);
  const canProvision = Boolean(
    status?.configured && status.provisioning_enabled && !status.instance_exists,
  );

  return (
    <div style={{ marginTop: 14, padding: 12, border: '1px solid var(--color-border)', borderRadius: 8, background: 'var(--color-bg)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600 }}>Evolution API · WhatsApp</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 3 }}>
            Transporte oficial do Agent Host. A chave fica somente no backend.
          </div>
        </div>
        <span style={{ fontSize: 11, color: status?.connected ? 'var(--color-success)' : 'var(--color-text-secondary)' }}>
          {describe(status)}
        </span>
      </div>

      {status?.instance_name && (
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--color-text-secondary)' }}>
          Instância: <code>{status.instance_name}</code>
        </div>
      )}

      {qrDataUrl && !status?.connected && (
        <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <div style={{ background: '#fff', padding: 8, borderRadius: 6 }}>
            <img src={qrDataUrl} alt="QR Code para conectar o WhatsApp via Evolution API" width={280} height={280} />
          </div>
          <div style={{ maxWidth: 260, fontSize: 11, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
            No WhatsApp, abra <strong>Dispositivos conectados</strong>, toque em <strong>Conectar dispositivo</strong> e leia este código.
            {qr?.state && <div style={{ marginTop: 6 }}>Estado da sessão: {qr.state}</div>}
          </div>
        </div>
      )}

      {status?.state === 'not_provisioned' && (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--color-warning)' }}>
          A API está instalada, mas nenhuma instância foi criada. A criação/pairing é uma etapa explícita e não acontece ao abrir esta tela.
        </div>
      )}
      {status?.connected && (
        <div role="status" style={{ marginTop: 10, fontSize: 11, color: 'var(--color-success)' }}>
          Sessão Evolution conectada. O envio continua sujeito à Policy e à aprovação do Agent Host.
        </div>
      )}
      {error && <div style={{ marginTop: 10, fontSize: 11, color: 'var(--color-error)' }}>{error}</div>}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
        {status?.state === 'not_provisioned' && (
          <button
            type="button"
            onClick={() => void createInstance()}
            disabled={provisioning || !canProvision}
            style={{
              padding: '8px 12px', border: '1px solid var(--color-accent)', borderRadius: 6,
              background: provisioning || !canProvision ? 'var(--color-disabled-bg)' : 'transparent',
              color: 'var(--color-text)', fontSize: 12,
              cursor: provisioning || !canProvision ? 'default' : 'pointer',
            }}
          >
            {provisioning ? 'Criando sessão…' : canProvision ? 'Criar sessão para gerar QR' : 'Provisioning desabilitado'}
          </button>
        )}
        <button
          type="button"
          onClick={() => void showQr()}
          disabled={busy || !canRequestQr}
          style={{
            padding: '8px 12px', border: '1px solid var(--color-accent)', borderRadius: 6,
            background: busy || !canRequestQr ? 'var(--color-disabled-bg)' : 'transparent',
            color: 'var(--color-text)', fontSize: 12,
            cursor: busy || !canRequestQr ? 'default' : 'pointer',
          }}
        >
          {busy ? 'Carregando QR…' : status?.connected ? 'Sessão conectada' : 'Mostrar QR Code'}
        </button>
      </div>
    </div>
  );
}
