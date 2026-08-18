import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  GeminiLiveSession,
  type JarvisVoiceState,
} from '@/lib/gemini-live';
import {
  createJarvisLiveToken,
  fetchJarvisLiveStatus,
  JarvisLiveApiError,
  type JarvisLiveStatus,
  type JarvisOperationalEventType,
} from '@/lib/jarvis-api';
import { useAppStore } from '@/lib/store';
import type { Conversation } from '@/types';
import type { JarvisAgentAction } from '../api/types';
import { decideJarvisEdgeApproval } from '../api/client';
import type { JarvisEdgeApproval } from '../api/types';
import {
  edgeApprovalFromEvent,
  eventResolvesEdgeApproval,
} from '../approvals/edge';
import { agentEventView } from '../timeline/events';
import type { JarvisTimelineEntry } from '../timeline/types';
import { JarvisAgentCoordinator } from './coordinator';
import { buildJarvisAgentContext } from './context';

const STARTUP_TIMEOUT_MS = 30_000;

function withTimeout<T>(promise: Promise<T>, message: string, onTimeout: () => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      onTimeout();
      reject(new Error(message));
    }, STARTUP_TIMEOUT_MS);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });
}

function timelineId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useJarvisAgentSession() {
  const conversations = useAppStore((state) => state.conversations);
  const activeId = useAppStore((state) => state.activeId);
  const codexSyncStatus = useAppStore((state) => state.codexSyncStatus);
  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? null,
    [activeId, conversations],
  );
  const [sessionTarget, setSessionTarget] = useState<Conversation | null>(null);
  const [liveStatus, setLiveStatus] = useState<JarvisLiveStatus | null>(null);
  const [voiceState, setVoiceState] = useState<JarvisVoiceState>('offline');
  const [audioLevel, setAudioLevel] = useState(0);
  const [inputTranscript, setInputTranscript] = useState('');
  const [outputTranscript, setOutputTranscript] = useState('');
  const [textInput, setTextInput] = useState('');
  const [timeline, setTimeline] = useState<JarvisTimelineEntry[]>([]);
  const [approval, setApproval] = useState<JarvisAgentAction | null>(null);
  const [edgeApproval, setEdgeApproval] = useState<JarvisEdgeApproval | null>(null);
  const [edgeDecisionBusy, setEdgeDecisionBusy] = useState(false);
  const [credentialSlot, setCredentialSlot] = useState<'primary' | 'fallback' | null>(null);
  const [microphoneOn, setMicrophoneOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const liveRef = useRef<GeminiLiveSession | null>(null);
  const coordinatorRef = useRef<JarvisAgentCoordinator | null>(null);

  const addTimeline = useCallback((type: JarvisOperationalEventType, text: string) => {
    setTimeline((current) => [
      ...current.slice(-49),
      { id: timelineId(), type, text, time: Date.now() },
    ]);
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      setLiveStatus(await fetchJarvisLiveStatus());
    } catch (error) {
      addTimeline('error', error instanceof Error ? error.message : 'Backend indisponível.');
    }
  }, [addTimeline]);

  useEffect(() => {
    void refreshStatus();
    return () => {
      void coordinatorRef.current?.close();
      coordinatorRef.current = null;
      void liveRef.current?.close();
      liveRef.current = null;
    };
  }, [refreshStatus]);

  const start = useCallback(async () => {
    if (liveRef.current || busy) return;
    const target = activeConversation;
    if (!target?.codexThreadId || !target.codexProjectCwd) {
      toast.error('Selecione primeiro um projeto e uma conversa em Codex target.');
      return;
    }
    setBusy(true);
    setVoiceState('connecting');
    setSessionTarget(target);
    const startup = new AbortController();
    const coordinator = new JarvisAgentCoordinator({
      onApproval: (action) => {
        setApproval(action);
        setVoiceState(action ? 'awaiting-approval' : liveRef.current ? 'listening' : 'offline');
      },
      onEvent: (event) => {
        const nested = edgeApprovalFromEvent(event);
        if (nested) {
          setEdgeApproval(nested);
          setVoiceState('awaiting-approval');
        } else {
          setEdgeApproval((current) => {
            if (current && eventResolvesEdgeApproval(event, current)) return null;
            return current;
          });
        }
        const view = agentEventView(event);
        addTimeline(view.type, view.text);
      },
      onNotice: (message) => addTimeline('system', message),
    });
    coordinatorRef.current = coordinator;
    try {
      const [token, agentSession] = await withTimeout(
        Promise.all([
          createJarvisLiveToken(),
          coordinator.open(target.codexProjectCwd, target.codexThreadId, startup.signal),
        ]),
        'A inicialização do Jarvis excedeu 30 segundos.',
        () => startup.abort(),
      );
      const context = [
        buildJarvisAgentContext(agentSession),
        `Projeto selecionado: ${target.codexProjectCwd}`,
        `Conversa selecionada: ${target.title}`,
      ].join('\n');
      setCredentialSlot(token.credential_slot);
      const live = new GeminiLiveSession(
        token,
        {
          onState: setVoiceState,
          onInputTranscript: (text, finished) => {
            setInputTranscript(text);
            if (!finished || !text.trim()) return;
            addTimeline('user', text.trim());
            void coordinator.commitFinalTurn(text).catch((error) => {
              addTimeline('error', error instanceof Error ? error.message : 'Falha no turno final.');
            });
          },
          onOutputTranscript: (text, finished) => {
            setOutputTranscript(text);
            if (finished && text.trim()) addTimeline('jarvis', text.trim());
          },
          onAudioLevel: setAudioLevel,
          onToolCall: (call) => coordinator.handleFunctionCall(call),
          onTurnComplete: () => undefined,
          onNotice: (message) => addTimeline('system', message),
          onError: (message) => addTimeline('error', message),
        },
        context,
        agentSession.manifest,
      );
      liveRef.current = live;
      await withTimeout(
        live.connect(),
        'O canal Gemini Live não respondeu a tempo.',
        () => void live.close(),
      );
      await live.startMicrophone();
      setMicrophoneOn(true);
      addTimeline(
        'system',
        token.fallback_active
          ? 'Jarvis online com credencial técnica de fallback.'
          : `Jarvis Agent online com ${agentSession.manifest.length} ferramentas executáveis.`,
      );
    } catch (error) {
      startup.abort();
      await coordinator.close();
      await liveRef.current?.close();
      coordinatorRef.current = null;
      liveRef.current = null;
      setApproval(null);
      setEdgeApproval(null);
      setMicrophoneOn(false);
      setCredentialSlot(null);
      setSessionTarget(null);
      setVoiceState('error');
      const message = error instanceof Error ? error.message : 'Falha ao iniciar Jarvis.';
      addTimeline('error', message);
      if (error instanceof JarvisLiveApiError && error.commandPreserved) {
        addTimeline('system', 'O comando pendente foi preservado pelo backend.');
      }
    } finally {
      setBusy(false);
      void refreshStatus();
    }
  }, [activeConversation, addTimeline, busy, refreshStatus]);

  const stop = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    await coordinatorRef.current?.close();
    coordinatorRef.current = null;
    await liveRef.current?.close();
    liveRef.current = null;
    setApproval(null);
    setEdgeApproval(null);
    setCredentialSlot(null);
    setMicrophoneOn(false);
    setSessionTarget(null);
    setVoiceState('offline');
    addTimeline('session', 'Sessão encerrada; callbacks antigos foram invalidados.');
    setBusy(false);
  }, [addTimeline, busy]);

  const toggleMicrophone = useCallback(async () => {
    const live = liveRef.current;
    if (!live) return;
    try {
      if (microphoneOn) await live.stopMicrophone();
      else await live.startMicrophone();
      setMicrophoneOn(!microphoneOn);
    } catch (error) {
      addTimeline('error', error instanceof Error ? error.message : 'Microfone indisponível.');
    }
  }, [addTimeline, microphoneOn]);

  const sendText = useCallback(() => {
    const text = textInput.trim();
    const live = liveRef.current;
    const coordinator = coordinatorRef.current;
    if (!text || !live || !coordinator) return;
    addTimeline('user', text);
    void coordinator.commitFinalTurn(text).then(
      () => live.sendText(text),
      (error) => addTimeline('error', error instanceof Error ? error.message : 'Falha na mensagem.'),
    );
    setTextInput('');
  }, [addTimeline, textInput]);

  const decide = useCallback(async (decision: 'approve' | 'deny') => {
    if (!coordinatorRef.current || !approval) return;
    if (decision === 'approve') {
      setApproval({ ...approval, state: 'DISPATCHING', status: 'dispatching' });
      setVoiceState('executing');
    }
    const result = await coordinatorRef.current.decide(decision);
    addTimeline(
      result.status === 'error' ? 'error' : 'approval',
      `Decisão visual: ${String(result.status ?? decision)}`,
    );
    setVoiceState(liveRef.current ? 'listening' : 'offline');
  }, [addTimeline, approval]);

  const decideEdge = useCallback(async (decision: 'approve' | 'deny') => {
    if (!edgeApproval || edgeDecisionBusy) return;
    setEdgeDecisionBusy(true);
    try {
      const result = await decideJarvisEdgeApproval(edgeApproval, decision);
      setEdgeApproval(null);
      addTimeline('approval', `Permissão local: ${String(result.state ?? decision)}`);
      setVoiceState(liveRef.current ? 'executing' : 'offline');
    } catch (error) {
      addTimeline('error', error instanceof Error ? error.message : 'Falha na permissão local.');
    } finally {
      setEdgeDecisionBusy(false);
    }
  }, [addTimeline, edgeApproval, edgeDecisionBusy]);

  return {
    activeConversation: sessionTarget ?? activeConversation,
    liveStatus,
    voiceState,
    audioLevel,
    inputTranscript,
    outputTranscript,
    textInput,
    timeline,
    approval,
    edgeApproval,
    edgeDecisionBusy,
    credentialSlot,
    microphoneOn,
    busy,
    codexSyncStatus,
    setTextInput,
    start,
    stop,
    toggleMicrophone,
    sendText,
    approve: () => decide('approve'),
    deny: () => decide('deny'),
    approveEdge: () => decideEdge('approve'),
    denyEdge: () => decideEdge('deny'),
  };
}
