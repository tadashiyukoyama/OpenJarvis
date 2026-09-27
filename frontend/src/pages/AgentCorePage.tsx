import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pause, Play, Square, Send, ShieldCheck, Mic, MicOff } from 'lucide-react';
import {
  controlAgentHost,
  decideAgentHostApproval,
  fetchAgentHostHistory,
  fetchAgentHostArtifacts,
  fetchAgentHostStatus,
  requestAgentHostApproval,
  sendAgentHostMessage,
  type AgentHostApproval,
  type AgentHostArtifact,
  type AgentHostEvent,
  type AgentHostStatus,
} from '../features/agent-host/client';
import { EvolutionWhatsAppPanel } from '../components/setup/EvolutionWhatsAppPanel';
import './AgentCorePage.css';

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionFactory = new () => SpeechRecognitionLike;

function conversationKey(): string {
  const key = 'openjarvis-agent-host-conversation';
  try {
    const existing = localStorage.getItem(key);
    if (existing) return existing;
    const value = globalThis.crypto?.randomUUID?.() ?? `owner-${Date.now().toString(36)}`;
    localStorage.setItem(key, value);
    return value;
  } catch {
    return 'owner-local';
  }
}

function stateLabel(status: string): string {
  return {
    starting: 'Inicializando',
    working: 'Trabalhando',
    waiting: 'Aguardando',
    paused: 'Pausado',
    stopped: 'Parado',
    completed: 'Concluído',
    blocked: 'Bloqueado',
    error: 'Erro',
  }[status] ?? status;
}

export function AgentCorePage() {
  const conversationId = useMemo(conversationKey, []);
  const [status, setStatus] = useState<AgentHostStatus | null>(null);
  const [events, setEvents] = useState<AgentHostEvent[]>([]);
  const [artifacts, setArtifacts] = useState<AgentHostArtifact[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [voiceListening, setVoiceListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const spokenRef = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, history, artifactSnapshot] = await Promise.all([
        fetchAgentHostStatus(conversationId),
        fetchAgentHostHistory(conversationId),
        fetchAgentHostArtifacts(conversationId),
      ]);
      setStatus(nextStatus);
      setEvents(history.events);
      setArtifacts(artifactSnapshot.artifacts);
    } catch (error) {
      setStatus((current) => current ?? {
        status: 'error', run_id: null, objective: null, budget: null,
        conversation_id: conversationId, latest_activity: null,
        last_error: error instanceof Error ? error.message : 'Agent Host indisponível',
        pending_approval: null, principal_id: 'owner',
      });
    }
  }, [conversationId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    for (const event of events) {
      if (event.role !== 'assistant' || !event.content || spokenRef.current.has(event.event_id)) continue;
      spokenRef.current.add(event.event_id);
      if ('speechSynthesis' in window) {
        const utterance = new SpeechSynthesisUtterance(event.content);
        utterance.lang = 'pt-BR';
        window.speechSynthesis.speak(utterance);
      }
    }
  }, [events]);

  const submit = useCallback(async () => {
    const text = message.trim();
    if (!text || busy) return;
    setBusy(true);
    setMessage('');
    try {
      await sendAgentHostMessage(conversationId, text);
      await refresh();
    } catch (error) {
      setVoiceError(error instanceof Error ? error.message : 'Falha ao enviar mensagem.');
    } finally {
      setBusy(false);
    }
  }, [busy, conversationId, message, refresh]);

  const control = useCallback(async (command: 'pause' | 'continue' | 'stop') => {
    if (busy) return;
    setBusy(true);
    try {
      await controlAgentHost(command);
      await refresh();
    } catch (error) {
      setVoiceError(error instanceof Error ? error.message : 'Falha no controle do Host.');
    } finally {
      setBusy(false);
    }
  }, [busy, refresh]);

  const toggleVoice = useCallback(() => {
    if (voiceListening) {
      recognitionRef.current?.stop();
      setVoiceListening(false);
      return;
    }
    const SpeechRecognition = (window as unknown as { SpeechRecognition?: SpeechRecognitionFactory; webkitSpeechRecognition?: SpeechRecognitionFactory }).SpeechRecognition
      ?? (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionFactory }).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceError('STT do navegador não está disponível neste ambiente.');
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = 'pt-BR';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let transcript = '';
      for (let index = 0; index < event.results.length; index += 1) transcript += event.results[index][0].transcript;
      setMessage(transcript);
    };
    recognition.onerror = () => {
      setVoiceError('Falha na captura de voz.');
      setVoiceListening(false);
    };
    recognition.onend = () => setVoiceListening(false);
    recognitionRef.current = recognition;
    setVoiceError(null);
    setVoiceListening(true);
    recognition.start();
  }, [voiceListening]);

  const approval: AgentHostApproval | null = status?.pending_approval ?? null;
  const requestApproval = useCallback(async () => {
    try {
      await requestAgentHostApproval({ kind: 'safe_test', description: 'Aprovação visual sem efeito externo' });
      await refresh();
    } catch (error) {
      setVoiceError(error instanceof Error ? error.message : 'Falha ao criar aprovação.');
    }
  }, [refresh]);

  const decideApproval = useCallback(async (decision: 'approve' | 'deny') => {
    if (!approval) return;
    try {
      await decideAgentHostApproval(approval.approval_id, decision);
      await refresh();
    } catch (error) {
      setVoiceError(error instanceof Error ? error.message : 'Falha ao decidir aprovação.');
    }
  }, [approval, refresh]);

  return (
    <main className="agent-core-page">
      <header className="agent-core-header">
        <div>
          <p className="agent-core-kicker">OPENJARVIS · AGENT HOST</p>
          <h1>Agente do proprietário</h1>
          <p className="agent-core-subtitle">Codex é o único cérebro. Esta interface apenas transporta, autentica e mostra o estado.</p>
        </div>
        <div className="agent-core-identity"><ShieldCheck size={16} /> principal_id: owner</div>
      </header>

      <section className="agent-core-status" aria-live="polite">
        <div className="agent-core-status-main"><span className={`agent-core-dot ${status?.status === 'working' ? 'active' : ''}`} />{stateLabel(status?.status ?? 'starting')}</div>
        <div className="agent-core-status-meta"><span>run: {status?.run_id ?? '—'}</span><span>conversa: {conversationId}</span></div>
        {status?.objective ? <p>{status.objective}</p> : null}
        {status?.budget ? <small>turns {String(status.budget.turns_consumed ?? 0)} · tools {String(status.budget.tool_calls_consumed ?? 0)} · limite {String(status.budget.max_turns ?? '—')}</small> : null}
      </section>

      <section className="agent-core-channel" aria-label="WhatsApp Evolution API">
        <h2>WhatsApp · Evolution API</h2>
        <p>Canal externo do mesmo Agent Host. O provider ativo é a Evolution API.</p>
        <EvolutionWhatsAppPanel />
      </section>

      <section className="agent-core-controls" aria-label="Controles do agente">
        <button type="button" onClick={() => void control('pause')} disabled={busy}><Pause size={15} /> Pausar</button>
        <button type="button" onClick={() => void control('continue')} disabled={busy}><Play size={15} /> Continuar</button>
        <button type="button" onClick={() => void control('stop')} disabled={busy} className="danger"><Square size={15} /> Parar</button>
        <button type="button" onClick={() => void requestApproval()} disabled={busy}><ShieldCheck size={15} /> Testar aprovação</button>
      </section>

      <section className="agent-core-conversation" aria-label="Conversa do agente">
        {events.length === 0 ? <p className="agent-core-empty">Envie uma mensagem para acordar o Agent Host.</p> : events.map((event) => (
          <article className={`agent-core-message ${event.role}`} key={`${event.sequence}-${event.event_id}`}>
            <span>{event.role === 'owner' ? 'Você' : 'Codex'}</span>
            <p>{event.content}</p>
            <time>{new Date(event.created_at).toLocaleTimeString('pt-BR')}</time>
          </article>
        ))}
      </section>

      <section className="agent-core-artifacts" aria-label="Artefatos da conversa">
        <h2>Artefatos</h2>
        {artifacts.length === 0 ? <p className="agent-core-empty">Nenhum artefato registrado.</p> : artifacts.map((artifact) => (
          <article key={artifact.artifact_id} className="agent-core-artifact">
            <strong>{artifact.filename}</strong>
            <span>{artifact.mime_type} · {Math.round(artifact.size / 1024)} KB · {artifact.status}</span>
            <small>{artifact.source} · {new Date(artifact.created_at).toLocaleString('pt-BR')}</small>
          </article>
        ))}
      </section>

      {approval ? <section className="agent-core-approval" aria-label="Aprovação pendente">
        <strong>Aprovação visual pendente</strong>
        <code>{approval.preview_hash}</code>
        <div><button type="button" onClick={() => void decideApproval('approve')}>Aprovar</button><button type="button" onClick={() => void decideApproval('deny')} className="danger">Recusar</button></div>
      </section> : null}

      <section className="agent-core-composer">
        <button type="button" onClick={toggleVoice} aria-label={voiceListening ? 'Parar microfone' : 'Iniciar microfone'} className={voiceListening ? 'voice-active' : ''}>{voiceListening ? <MicOff size={18} /> : <Mic size={18} />}</button>
        <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder="Fale ou escreva para o agente…" rows={2} />
        <button type="button" onClick={() => void submit()} disabled={busy || !message.trim()} aria-label="Enviar"><Send size={18} /></button>
      </section>
      {voiceError ? <p className="agent-core-error" role="alert">{voiceError}</p> : null}
    </main>
  );
}
