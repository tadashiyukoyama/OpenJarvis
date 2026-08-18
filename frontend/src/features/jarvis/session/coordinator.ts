import type { GeminiFunctionCall } from '@/lib/gemini-live';
import {
  closeJarvisAgentSession,
  commitJarvisAgentTurn,
  createJarvisAgentSession,
  decideJarvisAgentAction,
  JarvisAgentApiError,
  proposeJarvisAgentAction,
  streamJarvisAgentEvents,
} from '../api/client';
import type {
  JarvisAgentAction,
  JarvisAgentEvent,
  JarvisAgentSession,
  JsonObject,
} from '../api/types';

export interface JarvisAgentTransport {
  createSession: typeof createJarvisAgentSession;
  commitTurn: typeof commitJarvisAgentTurn;
  propose: typeof proposeJarvisAgentAction;
  decide: typeof decideJarvisAgentAction;
  close: typeof closeJarvisAgentSession;
  streamEvents: typeof streamJarvisAgentEvents;
}

export interface JarvisAgentCoordinatorCallbacks {
  onApproval: (action: JarvisAgentAction | null) => void;
  onEvent: (event: JarvisAgentEvent) => void;
  onNotice: (message: string) => void;
}

interface PendingDecision {
  action: JarvisAgentAction;
  promise: Promise<JsonObject>;
  resolve: (result: JsonObject) => void;
  timer: ReturnType<typeof setTimeout> | null;
}

const defaultTransport: JarvisAgentTransport = {
  createSession: createJarvisAgentSession,
  commitTurn: commitJarvisAgentTurn,
  propose: proposeJarvisAgentAction,
  decide: decideJarvisAgentAction,
  close: closeJarvisAgentSession,
  streamEvents: streamJarvisAgentEvents,
};

function uniqueId(prefix: string): string {
  const value = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}_${value}`;
}

function errorResult(error: unknown): JsonObject {
  if (error instanceof JarvisAgentApiError) {
    return { status: 'error', code: error.code, message: error.message };
  }
  return {
    status: 'error',
    code: 'JARVIS_AGENT_UNAVAILABLE',
    message: error instanceof Error ? error.message : 'Jarvis Agent indisponível.',
  };
}

function functionResult(action: JarvisAgentAction): JsonObject {
  const adapterResult = action.result ?? {};
  const external = /^(email|gmail|whatsapp|codex)\./.test(action.tool_id);
  return {
    status: action.status,
    action_id: action.action_id,
    ...(action.job ? { job_id: action.job.job_id } : {}),
    ...(action.summary ? { summary: action.summary } : {}),
    ...(action.error_code ? { code: action.error_code } : {}),
    result_trust: external ? 'external_untrusted_data' : 'internal_metadata',
    result: adapterResult,
  };
}

export class JarvisAgentCoordinator {
  private session: JarvisAgentSession | null = null;
  private closed = true;
  private latestTurnId: string | undefined;
  private turnQueue: Promise<void> = Promise.resolve();
  private pending: PendingDecision | null = null;
  private decisionInFlight = false;
  private eventAbort: AbortController | null = null;
  private eventCursor = 0;

  constructor(
    private readonly callbacks: JarvisAgentCoordinatorCallbacks,
    private readonly transport: JarvisAgentTransport = defaultTransport,
  ) {}

  get activeSession(): JarvisAgentSession | null {
    return this.session;
  }

  get pendingApproval(): JarvisAgentAction | null {
    return this.pending?.action ?? null;
  }

  async open(
    projectKey: string,
    codexThreadId: string,
    signal?: AbortSignal,
  ): Promise<JarvisAgentSession> {
    if (!this.closed || this.session) throw new Error('Já existe uma sessão Jarvis Agent ativa.');
    const session = await this.transport.createSession(projectKey, codexThreadId, signal);
    this.session = session;
    this.closed = false;
    this.latestTurnId = undefined;
    this.turnQueue = Promise.resolve();
    this.startEventStream();
    return session;
  }

  commitFinalTurn(transcript: string): Promise<void> {
    const session = this.requireSession();
    const text = transcript.trim();
    if (!text) return this.turnQueue;
    const turnId = uniqueId('turn');
    this.turnQueue = this.turnQueue.then(async () => {
      if (this.closed || this.session?.session_id !== session.session_id) return;
      await this.transport.commitTurn(session, turnId, text);
      this.latestTurnId = turnId;
    });
    return this.turnQueue;
  }

  async handleFunctionCall(call: GeminiFunctionCall): Promise<JsonObject> {
    try {
      const session = this.requireSession();
      await this.turnQueue;
      if (this.closed || this.session?.session_id !== session.session_id) {
        return { status: 'session_closed', code: 'SESSION_CLOSED' };
      }
      const functionCallId = call.id || uniqueId('function');
      const action = await this.transport.propose(
        session,
        functionCallId,
        call.name,
        call.args,
        this.latestTurnId,
      );
      if (action.status !== 'approval_required') return functionResult(action);
      return this.awaitVisualDecision(action);
    } catch (error) {
      return errorResult(error);
    }
  }

  async decide(decision: 'approve' | 'deny'): Promise<JsonObject> {
    const pending = this.pending;
    if (!pending || this.decisionInFlight) {
      return { status: 'no_pending_action', code: 'APPROVAL_REQUIRED' };
    }
    this.decisionInFlight = true;
    this.callbacks.onApproval({ ...pending.action, state: 'DISPATCHING', status: 'dispatching' });
    try {
      const result = await this.transport.decide(pending.action, decision);
      const response = functionResult(result);
      this.finishPending(pending, response);
      return response;
    } catch (error) {
      const response = errorResult(error);
      this.finishPending(pending, response);
      return response;
    } finally {
      this.decisionInFlight = false;
    }
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.eventAbort?.abort();
    this.eventAbort = null;
    const pending = this.pending;
    if (pending) {
      this.finishPending(pending, {
        status: 'session_closed',
        code: 'SESSION_CLOSED',
        action_id: pending.action.action_id,
      });
    }
    const session = this.session;
    this.session = null;
    this.latestTurnId = undefined;
    if (session) {
      try {
        await this.transport.close(session);
      } catch (error) {
        this.callbacks.onNotice(
          error instanceof Error ? error.message : 'Falha ao encerrar a sessão canônica.',
        );
      }
    }
  }

  private requireSession(): JarvisAgentSession {
    if (this.closed || !this.session) throw new Error('A sessão Jarvis Agent não está ativa.');
    return this.session;
  }

  private awaitVisualDecision(action: JarvisAgentAction): Promise<JsonObject> {
    if (this.pending?.action.action_id === action.action_id) return this.pending.promise;
    if (this.pending) {
      return Promise.resolve({
        status: 'action_pending',
        code: 'ACTION_PENDING',
        action_id: this.pending.action.action_id,
      });
    }
    let resolve!: (result: JsonObject) => void;
    const promise = new Promise<JsonObject>((done) => {
      resolve = done;
    });
    const pending: PendingDecision = { action, promise, resolve, timer: null };
    const expiresIn = Math.max(0, (action.expires_at ?? 0) * 1000 - Date.now());
    pending.timer = setTimeout(() => void this.expirePending(pending), expiresIn);
    this.pending = pending;
    this.callbacks.onApproval(action);
    return promise;
  }

  private async expirePending(pending: PendingDecision): Promise<void> {
    if (this.pending !== pending) return;
    try {
      const result = await this.transport.decide(pending.action, 'deny');
      this.finishPending(pending, functionResult(result));
    } catch (error) {
      this.finishPending(pending, errorResult(error));
    }
  }

  private finishPending(pending: PendingDecision, result: JsonObject): void {
    if (pending.timer) clearTimeout(pending.timer);
    if (this.pending === pending) {
      this.pending = null;
      this.callbacks.onApproval(null);
    }
    pending.resolve(result);
  }

  private startEventStream(): void {
    this.eventAbort?.abort();
    const controller = new AbortController();
    this.eventAbort = controller;
    void this.consumeEvents(controller);
  }

  private async consumeEvents(controller: AbortController): Promise<void> {
    while (!controller.signal.aborted && !this.closed) {
      try {
        this.eventCursor = await this.transport.streamEvents(
          this.eventCursor,
          (event) => {
            if (event.session_id === this.session?.session_id) this.callbacks.onEvent(event);
          },
          controller.signal,
        );
      } catch (error) {
        if (controller.signal.aborted || this.closed) return;
        this.callbacks.onNotice(
          error instanceof Error ? error.message : 'Canal de eventos Jarvis interrompido.',
        );
      }
      if (!controller.signal.aborted && !this.closed) {
        await new Promise((resolve) => setTimeout(resolve, 1_000));
      }
    }
  }
}

export const jarvisAgentCoordinatorInternals = { functionResult, errorResult };

export { buildJarvisAgentContext } from './context';
