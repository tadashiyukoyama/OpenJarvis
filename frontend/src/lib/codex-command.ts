import type { ChatMessage, MessageTelemetry, TokenUsage, ToolCallInfo } from '../types';
import { fetchCodexThreadHistory, requestCodexDesktopRefresh } from './api';
import { generateId, useAppStore } from './store';
import { streamChat } from './sse';

export interface CodexCommandProgress {
  phase: 'queued' | 'running' | 'complete' | 'error';
  text: string;
}

export interface SendCodexMessageOptions {
  conversationId?: string;
  /** Correlation id shared by Jarvis, the API request and the Codex message. */
  requestId?: string;
  origin?: 'chat' | 'jarvis';
  signal?: AbortSignal;
  onProgress?: (progress: CodexCommandProgress) => void;
}

interface ActiveDispatch {
  conversationId: string;
  token: symbol;
}

let activeDispatch: ActiveDispatch | null = null;

export function isCodexConversationDispatchActive(conversationId?: string | null): boolean {
  return Boolean(activeDispatch && (!conversationId || activeDispatch.conversationId === conversationId));
}

function parseEventData(data: string): any | null {
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

function isTransportPlaceholder(text: string): boolean {
  return /^comando\s+conclu[ií]do\s+pelo\s+codex\.?$/i.test(text.trim());
}

function legacyTransportError(text: string): string {
  const match = text.trim().match(/^error during generation:\s*(.+)$/is);
  return match?.[1]?.trim() ?? '';
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function recoverCanonicalAssistantResponse(
  threadId: string,
  userMessage: string,
  userMessageId?: string,
): Promise<string> {
  // The Codex Desktop persistence endpoint can become visible a few hundred
  // milliseconds after the compatibility SSE stream closes. Poll briefly so
  // Jarvis receives the real answer, never a transport acknowledgement.
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const history = await fetchCodexThreadHistory(threadId);
      const lastUserIndex = history.messages.reduce(
        (index, item, currentIndex) => {
          const matchesId = userMessageId && item.message_id === userMessageId;
          const matchesText = item.content.trim() === userMessage;
          return item.role === 'user' && (matchesId || matchesText) ? currentIndex : index;
        },
        -1,
      );
      const latestAssistant =
        lastUserIndex >= 0
          ? history.messages
              .slice(lastUserIndex + 1)
              .reverse()
              .find((item) => item.role === 'assistant' && item.content.trim())
          : undefined;
      if (latestAssistant && !isTransportPlaceholder(latestAssistant.content)) {
        return latestAssistant.content;
      }
    } catch {
      // A short-lived history failure is handled by the next bounded attempt.
    }
    if (attempt < 3) await sleep(250);
  }
  return '';
}

/**
 * The single OpenJarvis -> Codex conversation dispatcher.
 *
 * Both the Chat input and Jarvis voice tool call this function. It owns message
 * insertion, the exact `/v1/chat/completions` request, stream rendering and
 * release of the per-app execution lock. No second Jarvis transport exists.
 */
export async function sendCodexConversationMessage(
  rawMessage: string,
  options: SendCodexMessageOptions = {},
): Promise<string> {
  const message = rawMessage.trim();
  if (!message) throw new Error('A mensagem para o Codex está vazia.');

  const initial = useAppStore.getState();
  const conversationId = options.conversationId ?? initial.activeId;
  const conversation = initial.conversations.find(
    (candidate) => candidate.id === conversationId,
  );
  if (!conversationId || !conversation?.codexThreadId || !conversation.codexProjectCwd) {
    throw new Error('Selecione um projeto e uma conversa Codex antes de enviar.');
  }
  if (activeDispatch) {
    throw new Error('O Codex já está executando outra solicitação enviada pelo OpenJarvis.');
  }

  // `streamState` is presentation state, not a durable busy signal. If there is
  // no dispatcher owner, a true value is stale (for example after route/HMR
  // transition) and must not block the selected Codex thread forever.
  if (initial.streamState.isStreaming) initial.resetStream();

  const dispatchToken = Symbol('codex-dispatch');
  activeDispatch = { conversationId, token: dispatchToken };
  const startedAt = Date.now();
  const model = initial.selectedModel || conversation.model || 'codex';
  let elapsedTimer: ReturnType<typeof setInterval> | null = null;
  let accumulated = '';
  let usage: TokenUsage | undefined;
  let ttftMs: number | undefined;
  const toolCalls: ToolCallInfo[] = [];

  try {
    const userMessage: ChatMessage = {
      id: options.requestId ?? generateId(),
      role: 'user',
      content: message,
      timestamp: Date.now(),
    };
    initial.addMessage(conversationId, userMessage);
    const latestConversation = useAppStore
      .getState()
      .conversations.find((candidate) => candidate.id === conversationId);
    const apiMessages = (latestConversation?.messages ?? []).map((item) => ({
      role: item.role,
      content: item.content,
    }));
    initial.addMessage(conversationId, {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    });

    initial.setStreamState({
      isStreaming: true,
      phase: 'Delegando ao Codex...',
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    });
    elapsedTimer = setInterval(() => {
      useAppStore.getState().setStreamState({ elapsedMs: Date.now() - startedAt });
    }, 100);
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: `Request (${options.origin ?? 'chat'}): request_id=${userMessage.id} text_length=${message.length} model=${model}`,
    });
    options.onProgress?.({ phase: 'queued', text: message });
    options.onProgress?.({ phase: 'running', text: message });

    let lastFlush = 0;
    for await (const event of streamChat(
      {
        model,
        messages: apiMessages,
        stream: true,
        temperature: initial.settings.temperature,
        max_tokens: initial.settings.maxTokens,
        conversation_id: conversationId,
        conversation_scope: conversation.codexProjectCwd,
        codex_thread_id: conversation.codexThreadId,
        codex_project_cwd: conversation.codexProjectCwd,
        codex_client_user_message_id: userMessage.id,
      },
      options.signal,
    )) {
      const data = parseEventData(event.data);
      if (event.event === 'error') {
        const detail =
          data && typeof data.detail === 'string' && data.detail.trim()
            ? data.detail.trim()
            : 'Falha no turno do Codex.';
        throw new Error(detail);
      }
      if (event.event === 'agent_turn_start') {
        useAppStore.getState().setStreamState({ phase: 'Codex analisando...' });
        continue;
      }
      if (event.event === 'inference_start') {
        useAppStore.getState().setStreamState({ phase: 'Codex respondendo...' });
        continue;
      }
      if (event.event === 'tool_call_start' && data) {
        const toolCall: ToolCallInfo = {
          id: generateId(),
          tool: String(data.tool ?? 'tool'),
          arguments: data.arguments || '',
          status: 'running',
        };
        toolCalls.push(toolCall);
        useAppStore.getState().setStreamState({
          phase: `Executando ${toolCall.tool}...`,
          activeToolCalls: [...toolCalls],
        });
        useAppStore.getState().updateLastAssistant(
          conversationId,
          accumulated,
          [...toolCalls],
        );
        continue;
      }
      if (event.event === 'tool_call_end' && data) {
        const toolCall = [...toolCalls]
          .reverse()
          .find((candidate) => candidate.tool === data.tool && candidate.status === 'running');
        if (toolCall) {
          toolCall.status = data.success ? 'success' : 'error';
          toolCall.latency = data.latency;
          toolCall.result = data.result;
        }
        useAppStore.getState().setStreamState({
          phase: 'Codex respondendo...',
          activeToolCalls: [...toolCalls],
        });
        useAppStore.getState().updateLastAssistant(
          conversationId,
          accumulated,
          [...toolCalls],
        );
        continue;
      }

      const delta = data?.choices?.[0]?.delta?.content;
      if (data?.usage) usage = data.usage;
      if (typeof delta === 'string') {
        if (ttftMs === undefined) ttftMs = Date.now() - startedAt;
        accumulated += delta;
        useAppStore.getState().setStreamState({ phase: '', content: accumulated });
        const now = Date.now();
        if (now - lastFlush >= 80) {
          useAppStore.getState().updateLastAssistant(
            conversationId,
            accumulated,
            toolCalls.length ? [...toolCalls] : undefined,
          );
          lastFlush = now;
        }
      }
      if (data?.choices?.[0]?.finish_reason === 'stop') break;
    }

    const legacyError = legacyTransportError(accumulated);
    if (legacyError) throw new Error(legacyError);

    if (!accumulated || isTransportPlaceholder(accumulated)) {
      // Codex owns the turn lifecycle and can persist the final response
      // before the compatibility SSE path emits its content delta. Recover
      // the canonical public answer instead of exposing a generic transport
      // acknowledgement in the Chat or Jarvis timeline.
      accumulated = await recoverCanonicalAssistantResponse(
        conversation.codexThreadId,
        message,
        userMessage.id,
      );
    }
    if (!accumulated) {
      throw new Error('O Codex concluiu o turno, mas a resposta não foi recebida.');
    }
    const totalMs = Date.now() - startedAt;
    const telemetry: MessageTelemetry = {
      engine: 'codex',
      model_id: model,
      total_ms: totalMs,
      ttft_ms: ttftMs,
      tokens_per_sec: usage?.completion_tokens
        ? usage.completion_tokens / Math.max(totalMs / 1000, 0.001)
        : undefined,
    };
    useAppStore.getState().updateLastAssistant(
      conversationId,
      accumulated,
      toolCalls.length ? [...toolCalls] : undefined,
      usage,
      telemetry,
    );
    if (initial.settings.refreshCodexDesktop !== false) {
      try {
        await requestCodexDesktopRefresh(conversation.codexThreadId);
      } catch (error) {
        useAppStore.getState().addLogEntry({
          timestamp: Date.now(),
          level: 'warn',
          category: 'server',
          message: `Codex Desktop refresh unavailable: ${
            error instanceof Error ? error.message : 'unknown error'
          }`,
        });
      }
    }
    options.onProgress?.({ phase: 'complete', text: accumulated });
    return accumulated;
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === 'AbortError';
    const detail = aborted
      ? 'Execução interrompida pelo usuário.'
      : error instanceof Error
        ? error.message
        : 'Falha ao enviar a mensagem ao Codex.';
    useAppStore.getState().updateLastAssistant(
      conversationId,
      aborted ? detail : `Falha de envio: ${detail}`,
    );
    options.onProgress?.({ phase: 'error', text: detail });
    throw error;
  } finally {
    if (elapsedTimer) clearInterval(elapsedTimer);
    if (activeDispatch?.token === dispatchToken) activeDispatch = null;
    useAppStore.getState().resetStream();
  }
}
