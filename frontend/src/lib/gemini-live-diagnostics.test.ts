import { describe, expect, it, vi } from 'vitest';
import { GeminiLiveDiagnosticsCollector } from './gemini-live-diagnostics';

describe('Gemini Live client diagnostics', () => {
  it('reports delivery and playback counters without content or credentials', () => {
    const onDiagnostics = vi.fn();
    const collector = new GeminiLiveDiagnosticsCollector(
      () => ({
        state: 'playing',
        queuedMs: 240,
        prebufferMs: 180,
        underruns: 1,
        droppedSamples: 0,
        transport: 'worklet',
        transportReason: 'audio-worklet-active',
        audioContextState: 'running',
        audioContextSampleRate: 48_000,
        baseLatencyMs: 10,
        outputLatencyMs: 20,
      }),
      () => ({
        voiceState: 'speaking',
        socket: { readyState: 1, bufferedAmount: 0 } as WebSocket,
      }),
      onDiagnostics,
    );

    collector.recordAudioChunk('AAAA');
    collector.recordInterruption();

    const diagnostic = onDiagnostics.mock.calls[onDiagnostics.mock.calls.length - 1]?.[0];
    expect(diagnostic).toMatchObject({
      schema_version: '1.0',
      audio_chunks: 1,
      interruptions: 1,
      underruns: 1,
      transport: 'worklet',
      transport_reason: 'audio-worklet-active',
    });
    expect(JSON.stringify(diagnostic)).not.toContain('AAAA');
    expect(diagnostic).not.toHaveProperty('transcript');
    expect(diagnostic).not.toHaveProperty('token');
  });
});
