import type { PcmPlaybackMetrics } from './gemini-live-audio';

export interface GeminiLiveClientDiagnostics {
  schema_version: '1.0';
  session_id: string;
  sequence: number;
  occurred_at: number;
  voice_state: string;
  socket_state: number;
  transport: PcmPlaybackMetrics['transport'];
  transport_reason: PcmPlaybackMetrics['transportReason'];
  audio_context_state: PcmPlaybackMetrics['audioContextState'];
  audio_context_sample_rate: number;
  base_latency_ms: number;
  output_latency_ms: number;
  audio_chunks: number;
  audio_bytes: number;
  last_chunk_gap_ms: number;
  max_chunk_gap_ms: number;
  chunk_gaps_over_250_ms: number;
  message_queue_max_delay_ms: number;
  queued_ms: number;
  prebuffer_ms: number;
  underruns: number;
  dropped_samples: number;
  interruptions: number;
  go_away_events: number;
  websocket_buffered_amount: number;
}

interface DiagnosticContext {
  voiceState: string;
  socket: WebSocket | null;
}

const DIAGNOSTIC_INTERVAL_MS = 1_000;

export class GeminiLiveDiagnosticsCollector {
  private readonly sessionId = typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  private sequence = 0;
  private lastEmissionAt = 0;
  private audioChunks = 0;
  private audioBytes = 0;
  private lastAudioChunkAt = 0;
  private lastChunkGapMs = 0;
  private maxChunkGapMs = 0;
  private chunkGapsOver250Ms = 0;
  private messageQueueMaxDelayMs = 0;
  private interruptions = 0;
  private goAwayEvents = 0;

  constructor(
    private readonly playback: () => PcmPlaybackMetrics,
    private readonly context: () => DiagnosticContext,
    private readonly onDiagnostics?: (diagnostics: GeminiLiveClientDiagnostics) => void,
  ) {}

  recordPlayback(): void {
    this.emit();
  }

  recordAudioChunk(base64: string): void {
    const now = performance.now();
    if (this.lastAudioChunkAt > 0) {
      this.lastChunkGapMs = now - this.lastAudioChunkAt;
      this.maxChunkGapMs = Math.max(this.maxChunkGapMs, this.lastChunkGapMs);
      if (this.lastChunkGapMs > 250) this.chunkGapsOver250Ms += 1;
    }
    this.lastAudioChunkAt = now;
    this.audioChunks += 1;
    this.audioBytes += Math.max(0, Math.floor((base64.length * 3) / 4));
    this.emit();
  }

  recordQueueDelay(receivedAt: number): void {
    this.messageQueueMaxDelayMs = Math.max(
      this.messageQueueMaxDelayMs,
      performance.now() - receivedAt,
    );
  }

  recordInterruption(): void {
    this.interruptions += 1;
    this.emit(true);
  }

  recordGoAway(): void {
    this.goAwayEvents += 1;
    this.emit(true);
  }

  completeTurn(): void {
    this.lastAudioChunkAt = 0;
    this.emit(true);
  }

  emit(force = false): void {
    if (!this.onDiagnostics) return;
    const now = performance.now();
    if (!force && now - this.lastEmissionAt < DIAGNOSTIC_INTERVAL_MS) return;
    this.lastEmissionAt = now;
    this.sequence += 1;
    const metrics = this.playback();
    const context = this.context();
    this.onDiagnostics({
      schema_version: '1.0',
      session_id: this.sessionId,
      sequence: this.sequence,
      occurred_at: Date.now(),
      voice_state: context.voiceState,
      socket_state: context.socket?.readyState ?? WebSocket.CLOSED,
      transport: metrics.transport,
      transport_reason: metrics.transportReason,
      audio_context_state: metrics.audioContextState,
      audio_context_sample_rate: metrics.audioContextSampleRate,
      base_latency_ms: metrics.baseLatencyMs,
      output_latency_ms: metrics.outputLatencyMs,
      audio_chunks: this.audioChunks,
      audio_bytes: this.audioBytes,
      last_chunk_gap_ms: Math.round(this.lastChunkGapMs),
      max_chunk_gap_ms: Math.round(this.maxChunkGapMs),
      chunk_gaps_over_250_ms: this.chunkGapsOver250Ms,
      message_queue_max_delay_ms: Math.round(this.messageQueueMaxDelayMs),
      queued_ms: metrics.queuedMs,
      prebuffer_ms: metrics.prebufferMs,
      underruns: metrics.underruns,
      dropped_samples: metrics.droppedSamples,
      interruptions: this.interruptions,
      go_away_events: this.goAwayEvents,
      websocket_buffered_amount: context.socket?.bufferedAmount ?? 0,
    });
  }
}
