import { useEffect, useState } from 'react';
import { fetchJarvisAgentCatalog } from '@/features/jarvis/api/client';
import type { JarvisAgentCatalog, JarvisAgentProvider } from '@/features/jarvis/api/types';

const LABELS: Record<string, string> = {
  acelerachat_inboxes: 'AceleraChat · Todas as caixas',
  acelerachat_email: 'AceleraChat · E-mail',
  acelerachat_whatsapp: 'AceleraChat · WhatsApp',
  codex_desktop: 'Codex Desktop',
};

export function providerStatus(provider: JarvisAgentProvider): string {
  if (provider.connected) return 'conectado';
  if (provider.operational) {
    return provider.status === 'configured_not_probed'
      ? 'operacional · conexão não sondada'
      : 'operacional';
  }
  return provider.status.replace(/_/g, ' ');
}

export function JarvisProviderOverview() {
  const [catalog, setCatalog] = useState<JarvisAgentCatalog | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    void fetchJarvisAgentCatalog(controller.signal).then(
      setCatalog,
      (reason) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Catálogo Jarvis indisponível.');
        }
      },
    );
    return () => controller.abort();
  }, []);

  const sources = catalog?.sources.filter((source) =>
    ['acelerachat', 'email', 'whatsapp', 'codex'].includes(source.id),
  ) ?? [];
  return (
    <section className="hud-panel" style={{ padding: 14 }}>
      <div className="hud-label" style={{ marginBottom: 10 }}>PROVEDORES DO JARVIS</div>
      {error && <div style={{ color: 'var(--color-error)', fontSize: 12 }}>{error}</div>}
      {!catalog && !error && (
        <div style={{ color: 'var(--color-text-tertiary)', fontSize: 12 }}>
          Carregando catálogo canônico...
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
        {sources
          .flatMap((source) => source.providers.map((provider) => ({
            provider,
            sourceId: source.id,
          })))
          .map(({ provider, sourceId }) => {
            const tools = catalog?.tools.filter(
              (tool) => tool.source === sourceId && tool.available,
            ) ?? [];
            return (
              <div
                key={provider.id}
                style={{
                  border: '1px solid var(--color-border)',
                  borderRadius: 6,
                  padding: 9,
                }}
              >
                <strong style={{ display: 'block', fontSize: 12 }}>
                  {LABELS[provider.id] ?? provider.id}
                </strong>
                <span
                  style={{
                    fontSize: 11,
                    color: provider.operational
                      ? 'var(--color-success)'
                      : 'var(--color-text-tertiary)',
                  }}
                >
                  {providerStatus(provider)}
                </span>
                <details
                  style={{
                    marginTop: 7,
                    fontSize: 10,
                    color: 'var(--color-text-tertiary)',
                  }}
                >
                  <summary>{tools.length} ferramentas executáveis</summary>
                  {tools.length > 0 && (
                    <ul style={{ margin: '6px 0 0', paddingLeft: 16 }}>
                      {tools.map((tool) => (
                        <li key={tool.id}>{tool.name}</li>
                      ))}
                    </ul>
                  )}
                </details>
              </div>
            );
          })}
      </div>
      <p style={{ marginTop: 10, color: 'var(--color-text-tertiary)', fontSize: 11 }}>
        Todas as caixas são administradas no AceleraChat. O OpenJarvis usa apenas
        o contrato privado e nunca recebe tokens de canal pelo navegador.
      </p>
    </section>
  );
}
