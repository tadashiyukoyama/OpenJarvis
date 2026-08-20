import { Command, KeyRound, ShieldCheck } from 'lucide-react';
import type { JarvisAgentCatalog } from '../api/types';
import type { JarvisLiveStatus } from '@/lib/jarvis-api';
import { JARVIS_VOICE_NAME } from '@/lib/gemini-live';
import type { Conversation, CodexSyncStatus } from '@/types';

interface JarvisTargetPanelProps {
  conversation: Conversation | null;
  codexSyncStatus: CodexSyncStatus;
  liveStatus: JarvisLiveStatus | null;
  catalog: JarvisAgentCatalog | null;
  credentialSlot: 'primary' | 'fallback' | null;
}
export function JarvisTargetPanel({
  conversation,
  codexSyncStatus,
  liveStatus,
  catalog,
  credentialSlot,
}: JarvisTargetPanelProps) {
  const codexSyncLabel: Record<CodexSyncStatus, string> = {
    idle: 'inativo',
    connecting: 'conectando',
    live: 'conectado',
    degraded: 'conectado · histórico pendente',
    paused: 'pausado',
    retrying: 'reconectando',
  };
  const availableTools = catalog?.tools.filter((tool) => tool.available) ?? [];
  const codexDelegate = catalog?.tools.find((tool) => tool.id === 'codex.delegate');
  const delegateLabel = codexDelegate?.available
    ? 'disponível · aprovação visual'
    : codexDelegate ? 'bloqueada' : 'não catalogada';
  return (
    <aside className="jarvis-panel jarvis-target-panel">
      <div className="jarvis-panel-title"><Command size={15} /> ALVO OPERACIONAL</div>
      <div className="jarvis-target-name">
        {conversation?.codexProjectCwd?.split(/[\\/]/).pop() || 'Nenhum projeto'}
      </div>
      <div className="jarvis-target-thread">
        {conversation?.codexThreadId ? conversation.title : 'Selecione em Codex target'}
      </div>
      <div className="jarvis-signal-row">
        <span>Sincronização Codex</span>
        <strong className={['live', 'degraded'].includes(codexSyncStatus) ? 'is-ok' : ''}>
          {codexSyncLabel[codexSyncStatus]}
        </strong>
      </div>
      <div className="jarvis-signal-row">
        <span>Gemini principal</span>
        <strong className={liveStatus?.primary_configured ? 'is-ok' : ''}>
          {liveStatus?.primary_configured ? 'configurada' : 'ausente'}
        </strong>
      </div>
      <div className="jarvis-signal-row">
        <span>Fallback técnico</span>
        <strong className={liveStatus?.fallback_configured ? 'is-ok' : ''}>
          {liveStatus?.fallback_configured ? 'pronto' : 'ausente'}
        </strong>
      </div>
      <div className="jarvis-signal-row">
        <span>Voz Jarvis</span>
        <strong className="is-ok">{JARVIS_VOICE_NAME} · masculina</strong>
      </div>
      <div className="jarvis-signal-row">
        <span>Ferramentas executáveis</span>
        <strong
          className={availableTools.length ? 'is-ok' : 'is-warn'}
          title={availableTools.map((tool) => tool.id).join('\n')}
        >
          {catalog ? `${availableTools.length} de ${catalog.tools.length}` : 'carregando'}
        </strong>
      </div>
      <div className="jarvis-signal-row">
        <span>Delegação Codex</span>
        <strong className={codexDelegate?.available ? 'is-ok' : 'is-warn'}>
          {delegateLabel}
        </strong>
      </div>
      {credentialSlot && (
        <div className="jarvis-credential-badge">
          <KeyRound size={13} /> sessão: {credentialSlot}
        </div>
      )}
      {!liveStatus?.configured && (
        <div className="jarvis-config-note">
          Configure as chaves em <code>.private/env/gemini-live.env</code> e reinicie pelo launcher.
        </div>
      )}
      {codexDelegate?.unavailable_reason === 'external_mutations_disabled' && (
        <div className="jarvis-config-note">
          Ações externas estão bloqueadas pelo servidor; nenhuma delegação pode ser simulada.
        </div>
      )}
      {catalog && (
        <details className="jarvis-tool-catalog">
          <summary>Ver catálogo real</summary>
          <ul>
            {catalog.tools.map((tool) => (
              <li key={tool.id} title={tool.description}>
                <span>{tool.id}</span>
                <strong className={tool.available ? 'is-ok' : 'is-warn'}>
                  {tool.available ? 'ativa' : tool.unavailable_reason ?? 'indisponível'}
                </strong>
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="jarvis-policy-note">
        <ShieldCheck size={14} />
        <span>Mutação e Codex exigem o botão visual para o payload exato.</span>
      </div>
    </aside>
  );
}
