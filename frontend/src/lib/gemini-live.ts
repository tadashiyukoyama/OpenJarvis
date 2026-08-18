import type { JarvisLiveToken } from './jarvis-api';
import {
  arrayBufferToBase64,
  base64ToPcm,
  MicrophoneCapture,
  PcmPlayback,
  resampleToPcm16,
} from './gemini-live-audio';
import {
  GeminiLiveDiagnosticsCollector,
  type GeminiLiveClientDiagnostics,
} from './gemini-live-diagnostics';
import {
  buildGeminiLiveSetup,
  type GeminiFunctionDeclaration,
} from './gemini-live-setup';
import { GeminiTranscriptCoordinator } from './gemini-live-transcript';

export {
  buildGeminiLiveSetup,
  type GeminiFunctionDeclaration,
  JARVIS_VOICE_NAME,
} from './gemini-live-setup';
export type { GeminiLiveClientDiagnostics } from './gemini-live-diagnostics';

export type JarvisVoiceState =
  | 'offline'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'executing'
  | 'awaiting-approval'
  | 'reconnecting'
  | 'error';

export interface GeminiFunctionCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface GeminiLiveCallbacks {
  onState: (state: JarvisVoiceState) => void;
  onInputTranscript: (text: string, finished: boolean) => void;
  onOutputTranscript: (text: string, finished: boolean) => void;
  onAudioLevel: (level: number) => void;
  onToolCall: (call: GeminiFunctionCall) => Promise<Record<string, unknown>>;
  onTurnComplete: () => void;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
  onDiagnostics?: (diagnostics: GeminiLiveClientDiagnostics) => void;
}

const SETUP_TIMEOUT_MS = 15_000;

export class GeminiLiveSession {
  private token: JarvisLiveToken;
  private callbacks: GeminiLiveCallbacks;
  private socket: WebSocket | null = null;
  private readonly microphone: MicrophoneCapture;
  private readonly playback: PcmPlayback;
  private readonly diagnostics: GeminiLiveDiagnosticsCollector;
  private voiceState: JarvisVoiceState = 'offline';
  private sessionHandle = '';
  private manuallyClosed = false;
  private sessionGeneration = 0;
  private reconnecting = false;
  private readonly sessionContext: string;
  private readonly manifest: GeminiFunctionDeclaration[];
  private messageQueue: Promise<void> = Promise.resolve();
  private toolQueue: Promise<void> = Promise.resolve();
  private toolCallResults = new Map<string, Promise<Record<string, unknown>>>();
  private readonly transcript: GeminiTranscriptCoordinator;

  constructor(
    token: JarvisLiveToken,
    callbacks: GeminiLiveCallbacks,
    sessionContext = '',
    manifest: GeminiFunctionDeclaration[] = [],
  ) {
    this.token = token;
    this.callbacks = callbacks;
    this.sessionContext = sessionContext;
    this.manifest = manifest;
    this.playback = new PcmPlayback(() => this.diagnostics.recordPlayback());
    this.diagnostics = new GeminiLiveDiagnosticsCollector(
      () => this.playback.snapshot(),
      () => ({ voiceState: this.voiceState, socket: this.socket }),
      callbacks.onDiagnostics,
    );
    this.microphone = new MicrophoneCapture(
      (pcm) => {
        if (!this.isGenerationActive() || this.socket?.readyState !== WebSocket.OPEN) return;
        this.send({
          realtimeInput: {
            audio: {
              data: arrayBufferToBase64(pcm),
              mimeType: 'audio/pcm;rate=16000',
            },
          },
        });
      },
      (level) => this.callbacks.onAudioLevel(level),
    );
    this.transcript = new GeminiTranscriptCoordinator({
      onInput: (text, finished) => this.callbacks.onInputTranscript(text, finished),
      onOutput: (text, finished) => this.callbacks.onOutputTranscript(text, finished),
    });
  }

  async connect(): Promise<void> {
    const generation = ++this.sessionGeneration;
    this.manuallyClosed = false;
    this.transcript.reset();
    this.setState(this.reconnecting ? 'reconnecting' : 'connecting');
    const url = `${this.token.websocket_endpoint}?access_token=${encodeURIComponent(
      this.token.token,
    )}`;
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      let socket: WebSocket | null = null;
      const setupTimeout = setTimeout(() => {
        if (settled) return;
        settled = true;
        socket?.close();
        reject(new Error('O Gemini Live não concluiu a inicialização em 15 segundos.'));
      }, SETUP_TIMEOUT_MS);
      const resolveSetup = () => {
        if (settled) return;
        settled = true;
        clearTimeout(setupTimeout);
        resolve();
      };
      const rejectSetup = (error: Error) => {
        if (settled) return;
        settled = true;
        clearTimeout(setupTimeout);
        reject(error);
      };
      let liveSocket: WebSocket;
      try {
        liveSocket = new WebSocket(url);
      } catch (error) {
        rejectSetup(
          error instanceof Error
            ? error
            : new Error('Não foi possível abrir o canal Gemini Live.'),
        );
        return;
      }
      socket = liveSocket;
      this.socket = liveSocket;
      liveSocket.onopen = () => {
        try {
          liveSocket.send(
            JSON.stringify(
              buildGeminiLiveSetup(
                this.token.model,
                this.sessionHandle,
                this.sessionContext,
                this.manifest,
              ),
            ),
          );
        } catch (error) {
          rejectSetup(error instanceof Error ? error : new Error('Falha ao enviar a configuração do Gemini Live.'));
        }
      };
      liveSocket.onmessage = (event) => {
        if (!this.isGenerationActive(generation)) return;
        const receivedAt = performance.now();
        this.messageQueue = this.messageQueue
          .then(() =>
            this.handleMessage(event.data, () => {
              resolveSetup();
            }, generation, receivedAt),
          )
          .catch((error) => {
            if (!this.isGenerationActive(generation)) return;
            rejectSetup(
              error instanceof Error
                ? error
                : new Error('Falha ao processar a inicialização do Gemini Live.'),
            );
            this.callbacks.onError(
              error instanceof Error
                ? error.message
                : 'Falha ao processar uma mensagem do Gemini Live.',
            );
          });
      };
      liveSocket.onerror = () => {
        if (!this.isGenerationActive(generation)) return;
        rejectSetup(new Error('Falha ao conectar ao Gemini Live.'));
      };
      liveSocket.onclose = (event) => {
        if (!this.isGenerationActive(generation)) return;
        rejectSetup(new Error(event.reason || 'A sessão Gemini Live foi encerrada.'));
        if (this.manuallyClosed || this.reconnecting) return;
        this.setState('error');
        this.callbacks.onError(event.reason || 'A sessão Gemini Live foi encerrada.');
      };
    });
    this.reconnecting = false;
    this.setState('listening');
    this.diagnostics.emit(true);
  }

  private isGenerationActive(generation = this.sessionGeneration): boolean {
    return generation === this.sessionGeneration && !this.manuallyClosed;
  }

  private async handleMessage(
    data: unknown,
    onSetup: () => void,
    generation = this.sessionGeneration,
    receivedAt = performance.now(),
  ): Promise<void> {
    if (!this.isGenerationActive(generation)) return;
    this.diagnostics.recordQueueDelay(receivedAt);
    let text: string;
    if (data instanceof Blob) text = await data.text();
    else if (data instanceof ArrayBuffer) text = new TextDecoder().decode(data);
    else text = String(data);
    if (!this.isGenerationActive(generation)) return;
    let message: any;
    try {
      message = JSON.parse(text);
    } catch {
      return;
    }

    if (message.setupComplete) onSetup();
    if (message.sessionResumptionUpdate?.resumable) {
      this.sessionHandle = message.sessionResumptionUpdate.newHandle || '';
    }
    if (message.goAway) {
      this.diagnostics.recordGoAway();
      this.callbacks.onNotice('Renovando a conexão de voz sem perder o contexto.');
      void this.reconnect();
      return;
    }
    const content = message.serverContent;
    if (content?.interrupted) {
      this.diagnostics.recordInterruption();
      this.interruptPlayback();
    }
    if (content?.inputTranscription) {
      this.transcript.appendInput(content.inputTranscription.text || '');
    }
    if (content?.outputTranscription) {
      this.transcript.appendOutput(content.outputTranscription.text || '');
    }
    for (const part of content?.modelTurn?.parts ?? []) {
      if (!this.isGenerationActive(generation)) return;
      if (part.inlineData?.data) {
        this.diagnostics.recordAudioChunk(part.inlineData.data);
        this.setState('speaking');
        await this.playAudio(part.inlineData.data);
      }
    }
    if (!this.isGenerationActive(generation)) return;
    if (content?.generationComplete && !content?.turnComplete) {
      this.setState('speaking');
    }
    if (content?.turnComplete) {
      this.diagnostics.completeTurn();
      this.transcript.finalizeInput();
      this.callbacks.onTurnComplete();
      this.setState('listening');
    }
    if (message.toolCall?.functionCalls) {
      this.queueToolCalls(message.toolCall.functionCalls, generation);
    }
  }

  private queueToolCalls(calls: any[], generation = this.sessionGeneration): void {
    this.toolQueue = this.toolQueue
      .then(async () => {
        if (!this.isGenerationActive(generation)) return;
        await this.transcript.waitForInputBeforeTool();
        await this.handleToolCalls(calls, generation);
      })
      .catch((error) => {
        if (!this.isGenerationActive(generation)) return;
        this.callbacks.onError(
          error instanceof Error ? error.message : 'Falha ao processar ferramenta.',
        );
      });
  }

  private async handleToolCalls(
    calls: any[],
    generation = this.sessionGeneration,
  ): Promise<void> {
    if (!this.isGenerationActive(generation)) return;
    const responses = [];
    for (const raw of calls) {
      if (!this.isGenerationActive(generation)) return;
      const call: GeminiFunctionCall = {
        id: String(raw.id || ''),
        name: String(raw.name || ''),
        args: raw.args && typeof raw.args === 'object' ? raw.args : {},
      };
      let resultPromise = call.id ? this.toolCallResults.get(call.id) : undefined;
      if (resultPromise) {
        this.callbacks.onNotice(
          `Chamada Gemini ${call.id} já processada; resultado anterior reutilizado.`,
        );
      } else {
        resultPromise = Promise.resolve()
          .then(() => {
            if (!this.isGenerationActive(generation)) {
              return { status: 'session_closed', message: 'Sessão encerrada.' };
            }
            return this.callbacks.onToolCall(call);
          })
          .catch((error) => ({
            status: 'error',
            message: error instanceof Error ? error.message : 'Falha na ferramenta',
          }));
        if (call.id) {
          this.toolCallResults.set(call.id, resultPromise);
          this.limitToolCallCache();
        }
      }
      const result = await resultPromise;
      responses.push({
        id: call.id,
        name: call.name,
        response: { result },
      });
    }
    if (!this.isGenerationActive(generation)) return;
    this.send({ toolResponse: { functionResponses: responses } });
  }

  private limitToolCallCache(): void {
    while (this.toolCallResults.size > 256) {
      const oldest = this.toolCallResults.keys().next().value;
      if (oldest === undefined) return;
      this.toolCallResults.delete(oldest);
    }
  }

  async startMicrophone(): Promise<void> {
    await this.microphone.start();
    this.setState('listening');
  }

  async stopMicrophone(): Promise<void> {
    if (
      this.microphone.active &&
      !this.manuallyClosed &&
      this.socket?.readyState === WebSocket.OPEN
    ) {
      this.send({ realtimeInput: { audioStreamEnd: true } });
    }
    await this.microphone.stop();
  }

  sendText(text: string): void {
    this.send({ realtimeInput: { text } });
    this.setState('thinking');
  }

  private send(message: Record<string, unknown>): void {
    if (!this.isGenerationActive() || this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error('A sessão Gemini Live não está conectada.');
    }
    this.socket.send(JSON.stringify(message));
  }

  private async playAudio(base64: string): Promise<void> {
    await this.playback.play(base64);
  }

  private setState(state: JarvisVoiceState): void {
    this.voiceState = state;
    this.callbacks.onState(state);
  }

  interruptPlayback(): void {
    this.playback.interrupt();
  }

  private async reconnect(): Promise<void> {
    if (this.reconnecting || this.manuallyClosed) return;
    this.reconnecting = true;
    this.setState('reconnecting');
    this.sessionGeneration += 1;
    const previous = this.socket;
    this.socket = null;
    previous?.close(1000, 'session resumption');
    await new Promise((resolve) => window.setTimeout(resolve, 150));
    try {
      await this.connect();
    } catch (error) {
      this.setState('error');
      this.callbacks.onError(
        error instanceof Error ? error.message : 'Falha ao retomar o Gemini Live.',
      );
    }
  }

  async close(): Promise<void> {
    this.sessionGeneration += 1;
    this.manuallyClosed = true;
    this.transcript.invalidate();
    await this.stopMicrophone();
    this.socket?.close(1000, 'user closed');
    this.socket = null;
    await this.playback.close();
    this.setState('offline');
    this.diagnostics.emit(true);
  }
}

export const jarvisLiveInternals = {
  arrayBufferToBase64,
  base64ToPcm,
  resampleToPcm16,
};
