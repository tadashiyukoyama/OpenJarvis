import { Sparkles } from 'lucide-react';
import { JarvisApprovalPanel } from '../features/jarvis/approvals/JarvisApprovalPanel';
import { JarvisEdgeApprovalPanel } from '../features/jarvis/approvals/JarvisEdgeApprovalPanel';
import { JarvisTargetPanel } from '../features/jarvis/session/JarvisTargetPanel';
import { useJarvisAgentSession } from '../features/jarvis/session/useJarvisAgentSession';
import { JarvisVoiceCore } from '../features/jarvis/session/JarvisVoiceCore';
import { JarvisTimeline } from '../features/jarvis/timeline/JarvisTimeline';
import type { JarvisVoiceState } from '../lib/gemini-live';
import './JarvisPage.css';

const STATE_LABELS: Record<JarvisVoiceState, string> = {
  offline: 'Em espera',
  connecting: 'Inicializando',
  listening: 'Escutando',
  thinking: 'Interpretando',
  speaking: 'Falando',
  executing: 'Ação em execução',
  'awaiting-approval': 'Aguardando autorização',
  reconnecting: 'Reconectando',
  error: 'Atenção necessária',
};

const STATE_HINTS: Record<JarvisVoiceState, string> = {
  offline: 'Inicie uma sessão para conversar naturalmente.',
  connecting: 'Carregando manifesto, contexto e canal de voz.',
  listening: 'Pode falar. Você pode interromper Jarvis a qualquer momento.',
  thinking: 'Compreendendo contexto e intenção.',
  speaking: 'Resposta de áudio em tempo real.',
  executing: 'O payload autorizado está sendo processado uma única vez.',
  'awaiting-approval': 'Use os botões; confirmação falada não autoriza.',
  reconnecting: 'Retomando a sessão sem descartar o contexto.',
  error: 'Confira a linha operacional e tente novamente.',
};

export function JarvisPage() {
  const jarvis = useJarvisAgentSession();
  const connected = jarvis.voiceState !== 'offline' && jarvis.voiceState !== 'error';
  return (
    <section className={`jarvis-page jarvis-state-${jarvis.voiceState}`}>
      <div className="jarvis-grid" aria-hidden="true" />
      <div className="jarvis-scanline" aria-hidden="true" />
      <header className="jarvis-header">
        <div>
          <div className="jarvis-eyebrow"><Sparkles size={13} /> OPENJARVIS AGENT CORE</div>
          <h1>JARVIS</h1>
          <p>Gemini compreende. O backend decide. César autoriza. O adaptador executa.</p>
        </div>
        <div className="jarvis-header-status">
          <span className={`jarvis-status-dot ${connected ? 'is-live' : ''}`} />
          {STATE_LABELS[jarvis.voiceState]}
        </div>
      </header>
      <div className="jarvis-layout">
        <JarvisTargetPanel
          conversation={jarvis.activeConversation}
          codexSyncStatus={jarvis.codexSyncStatus}
          liveStatus={jarvis.liveStatus}
          catalog={jarvis.catalog}
          credentialSlot={jarvis.credentialSlot}
        />
        <JarvisVoiceCore
          voiceState={jarvis.voiceState}
          stateLabel={STATE_LABELS[jarvis.voiceState]}
          stateHint={STATE_HINTS[jarvis.voiceState]}
          audioLevel={jarvis.audioLevel}
          inputTranscript={jarvis.inputTranscript}
          outputTranscript={jarvis.outputTranscript}
          textInput={jarvis.textInput}
          microphoneOn={jarvis.microphoneOn}
          busy={jarvis.busy}
          configured={jarvis.liveStatus?.configured === true}
          onTextChange={jarvis.setTextInput}
          onStart={() => void jarvis.start()}
          onStop={() => void jarvis.stop()}
          onToggleMicrophone={() => void jarvis.toggleMicrophone()}
          onSendText={jarvis.sendText}
        />
        <JarvisTimeline entries={jarvis.timeline} />
      </div>
      {jarvis.edgeApproval ? (
        <JarvisEdgeApprovalPanel
          approval={jarvis.edgeApproval}
          busy={jarvis.edgeDecisionBusy}
          onApprove={() => void jarvis.approveEdge()}
          onDeny={() => void jarvis.denyEdge()}
        />
      ) : jarvis.approval ? (
        <JarvisApprovalPanel
          action={jarvis.approval}
          onApprove={() => void jarvis.approve()}
          onDeny={() => void jarvis.deny()}
        />
      ) : null}
    </section>
  );
}
