import { Command, KeyRound, ShieldCheck } from 'lucide-react';
import type { JarvisLiveStatus } from '@/lib/jarvis-api';
import { JARVIS_VOICE_NAME } from '@/lib/gemini-live';
import type { Conversation, CodexSyncStatus } from '@/types';

interface JarvisTargetPanelProps {
  conversation: Conversation | null;
  codexSyncStatus: CodexSyncStatus;
  liveStatus: JarvisLiveStatus | null;
  credentialSlot: 'primary' | 'fallback' | null;
}
export function JarvisTargetPanel({
  conversation,
  codexSyncStatus,
  liveStatus,
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
      <div className="jarvis-policy-note">
        <ShieldCheck size={14} />
        <span>Mutação e Codex exigem o botão visual para o payload exato.</span>
      </div>
    </aside>
  );
}
