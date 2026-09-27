import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bot,
  Check,
  Circle,
  LockKeyhole,
  MessageCircle,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import {
  fetchAgentHostHistory,
  fetchWhatsAppConversations,
  sendAgentHostMessage,
  sendWhatsAppOperatorReply,
  type AgentHostEvent,
  type WhatsAppConversationSummary,
} from '../features/agent-host/client';
import './WhatsAppInboxPage.css';

type ComposeMode = 'agent' | 'operator';

function eventLabel(role: string): string {
  if (role === 'channel') return 'Cliente';
  if (role === 'assistant') return 'Agente · Codex';
  if (role === 'operator') return 'Você · intervenção';
  return role;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

function freshKey(prefix: string): string {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
}

export function WhatsAppInboxPage() {
  const [conversations, setConversations] = useState<WhatsAppConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentHostEvent[]>([]);
  const [query, setQuery] = useState('');
  const [message, setMessage] = useState('');
  const [mode, setMode] = useState<ComposeMode>('agent');
  const [operatorConfirmed, setOperatorConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    const result = await fetchWhatsAppConversations();
    setConversations(result.conversations ?? []);
    setSelectedId((current) => {
      if (current && result.conversations.some((item) => item.conversation_id === current)) return current;
      return result.conversations[0]?.conversation_id ?? null;
    });
  }, []);

  const refreshHistory = useCallback(async () => {
    if (!selectedId) {
      setEvents([]);
      return;
    }
    const result = await fetchAgentHostHistory(selectedId);
    setEvents(result.events ?? []);
  }, [selectedId]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setError(null);
      await refreshList();
      await refreshHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Agent Host indisponível.');
    } finally {
      setRefreshing(false);
    }
  }, [refreshHistory, refreshList]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void Promise.all([refreshList(), refreshHistory()]).catch((cause) => {
        setError(cause instanceof Error ? cause.message : 'Falha ao atualizar a inbox.');
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [refresh, refreshHistory, refreshList]);

  const filteredConversations = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return conversations;
    return conversations.filter((item) =>
      `${item.display_label} ${item.conversation_id} ${item.last_message}`.toLowerCase().includes(normalized),
    );
  }, [conversations, query]);

  const selected = conversations.find((item) => item.conversation_id === selectedId) ?? null;
  const lastEvent = events[events.length - 1];
  const agentActive = lastEvent?.role === 'assistant' || selected?.last_role === 'assistant';

  const submit = useCallback(async () => {
    const text = message.trim();
    if (!selectedId || !text || busy) return;
    if (mode === 'operator' && !operatorConfirmed) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === 'operator') {
        await sendWhatsAppOperatorReply(selectedId, text, freshKey('operator-reply'));
      } else {
        // This mode only gives the Codex an owner instruction. The Codex
        // remains responsible for deciding whether and how to respond.
        await sendAgentHostMessage(selectedId, text, freshKey('inbox-owner'));
      }
      setMessage('');
      setOperatorConfirmed(false);
      await Promise.all([refreshList(), refreshHistory()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível enviar.');
    } finally {
      setBusy(false);
    }
  }, [busy, mode, message, operatorConfirmed, refreshHistory, refreshList, selectedId]);

  return (
    <main className="whatsapp-inbox-page">
      <header className="whatsapp-inbox-header">
        <div>
          <p className="whatsapp-inbox-kicker">OPENJARVIS · WHATSAPP</p>
          <h1>Inbox do agente</h1>
          <p className="whatsapp-inbox-subtitle">
            Acompanhe as conversas que passaram pelo Agent Host e intervenha sem criar um segundo canal.
          </p>
        </div>
        <div className="whatsapp-inbox-header-actions">
          <span className="whatsapp-inbox-security"><ShieldCheck size={15} /> Policy + idempotência ativas</span>
          <button type="button" className="whatsapp-icon-button" onClick={() => void refresh()} disabled={refreshing} aria-label="Atualizar conversas" title="Atualizar conversas">
            <RefreshCw size={17} className={refreshing ? 'whatsapp-spin' : ''} />
          </button>
        </div>
      </header>

      <section className="whatsapp-inbox-shell" aria-label="Conversas do WhatsApp">
        <aside className="whatsapp-conversation-panel">
          <div className="whatsapp-panel-heading">
            <div>
              <span className="whatsapp-panel-label">Conversas</span>
              <strong>{conversations.length}</strong>
            </div>
            <span className="whatsapp-connection"><Circle size={9} fill="currentColor" /> Agent Host</span>
          </div>
          <label className="whatsapp-search">
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">Buscar conversas</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar por conversa…" />
          </label>
          <div className="whatsapp-conversation-list">
            {filteredConversations.length === 0 ? (
              <div className="whatsapp-list-empty">
                <MessageCircle size={25} />
                <strong>Nenhuma conversa ainda</strong>
                <span>Quando uma mensagem chegar pelo WhatsApp, ela aparecerá aqui.</span>
              </div>
            ) : filteredConversations.map((conversation) => (
              <button
                type="button"
                key={conversation.conversation_id}
                className={`whatsapp-conversation-row ${selectedId === conversation.conversation_id ? 'selected' : ''}`}
                onClick={() => { setSelectedId(conversation.conversation_id); setEvents([]); }}
              >
                <span className="whatsapp-avatar"><UserRound size={17} /></span>
                <span className="whatsapp-conversation-copy">
                  <span className="whatsapp-conversation-topline"><strong>{conversation.display_label}</strong><time>{formatDate(conversation.last_activity_at)}</time></span>
                  <span className="whatsapp-conversation-preview">{conversation.last_message || 'Sem texto'}</span>
                  <span className="whatsapp-conversation-meta">{conversation.received_count} recebida{conversation.received_count === 1 ? '' : 's'} · {conversation.last_role === 'assistant' ? 'agente respondeu' : 'aguardando'}</span>
                </span>
              </button>
            ))}
          </div>
          <div className="whatsapp-privacy-note"><LockKeyhole size={14} /> Identidades aparecem como referências protegidas.</div>
        </aside>

        <section className="whatsapp-thread-panel" aria-label={selected ? `Conversa ${selected.display_label}` : 'Conversa selecionada'}>
          {selected ? (
            <>
              <header className="whatsapp-thread-header">
                <div className="whatsapp-thread-identity">
                  <span className="whatsapp-avatar large"><UserRound size={19} /></span>
                  <div><h2>{selected.display_label}</h2><span>{selected.conversation_id} · {agentActive ? 'agente ativo' : 'aguardando agente'}</span></div>
                </div>
                <div className="whatsapp-thread-state"><Bot size={15} /> Codex + Agent Host</div>
              </header>
              <div className="whatsapp-thread-banner"><ShieldCheck size={15} /><span>Esta conversa é correlacionada pelo Agent Host. O navegador não acessa JIDs ou credenciais do provider.</span></div>
              <div className="whatsapp-message-list">
                {events.length === 0 ? <div className="whatsapp-list-empty thread-empty"><MessageCircle size={26} /><strong>Sem mensagens carregadas</strong><span>O histórico desta conversa ainda está vazio ou o Host está indisponível.</span></div> : events.map((event) => (
                  <article key={`${event.sequence}-${event.event_id}`} className={`whatsapp-message-bubble ${event.role}`}>
                    <div className="whatsapp-message-label">{eventLabel(event.role)}<time>{formatTime(event.created_at)}</time></div>
                    <p>{event.content || 'Mídia/artefato recebido'}</p>
                    {event.payload?.status && event.role === 'operator' ? <small className={`whatsapp-send-status ${event.payload.status === 'completed' ? 'ok' : 'attention'}`}>{event.payload.status === 'completed' ? 'Enviado pelo gateway' : `Estado: ${String(event.payload.status)}`}</small> : null}
                  </article>
                ))}
              </div>
              <footer className="whatsapp-composer-area">
                <div className="whatsapp-compose-modes" role="tablist" aria-label="Modo de resposta">
                  <button type="button" role="tab" aria-selected={mode === 'agent'} className={mode === 'agent' ? 'active' : ''} onClick={() => { setMode('agent'); setOperatorConfirmed(false); }}><Bot size={15} /> Orientar agente</button>
                  <button type="button" role="tab" aria-selected={mode === 'operator'} className={mode === 'operator' ? 'active operator' : ''} onClick={() => setMode('operator')}><UserRound size={15} /> Responder como você</button>
                </div>
                <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder={mode === 'agent' ? 'Dê uma instrução ao Codex nesta conversa…' : 'Escreva a resposta que será enviada ao contato…'} rows={3} aria-label="Mensagem" />
                {mode === 'operator' ? <label className="whatsapp-confirm"><input type="checkbox" checked={operatorConfirmed} onChange={(event) => setOperatorConfirmed(event.target.checked)} /><span>Confirmo o envio desta mensagem pelo WhatsApp.</span><Check size={14} /></label> : <p className="whatsapp-compose-hint"><Bot size={14} /> O Codex decide a próxima ação; nada é enviado diretamente por este modo.</p>}
                <div className="whatsapp-compose-bottom"><span>{mode === 'operator' ? <><AlertTriangle size={14} /> O envio continua sujeito à Policy e ao gateway.</> : <><ShieldCheck size={14} /> Mensagem autenticada para o Agent Host.</>}</span><button type="button" className={`whatsapp-send-button ${mode === 'operator' ? 'operator' : ''}`} onClick={() => void submit()} disabled={busy || !message.trim() || (mode === 'operator' && !operatorConfirmed)}><Send size={16} />{busy ? 'Enviando…' : mode === 'operator' ? 'Confirmar e enviar' : 'Enviar ao agente'}</button></div>
              </footer>
            </>
          ) : <div className="whatsapp-no-selection"><MessageCircle size={34} /><h2>Selecione uma conversa</h2><p>A inbox será preenchida pelo histórico real do Agent Host.</p></div>}
        </section>
      </section>
      {error ? <p className="whatsapp-inbox-error" role="alert"><AlertTriangle size={15} /> {error}</p> : null}
    </main>
  );
}
